from pathlib import Path
from PySide6.QtCore import QFileSystemWatcher, QPoint, QSettings, QSignalBlocker, QThreadPool, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMenu, QMessageBox, QSplitter, QStatusBar, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)
from .parser import ParseError, read_document, replacement, validate
from .project import ModuleEntry, World, open_world
from .index_cache import ModuleIndexCache
from .indexing import IndexSignals, IndexWorldTask, ModuleIndexResult
from .navigation import Location, NavigationHistory, search_file, symbols_for_module
from .widgets.quick_dialog import QuickDialog
from .widgets.member_delegate import MemberDelegate
from .widgets.code_query_dialog import CodeQueryDialog
from .widgets.file_view import FileViewWindow
from .widgets.browser_lists import CategoryListWidget, MemberListWidget
from .workspace import Workspace
from .code_queries import callable_name_from_label, implementers, senders
from .structural import (
    StructuralEditError, add_class, add_function, add_method, convert_method_kind,
    create_package_init, delete_member, duplicate_member, move_member, rename_category,
)
from threading import Event
from .saving import atomic_write, changed
from .search import SearchMatch, find_all
from .widgets.editor import Editor
from .widgets.preferences_dialog import PreferencesDialog
from .widgets.replace_dialog import ReplaceDialog
from .widgets.diagnostics_panel import DiagnosticsPanel
from .widgets.typecheck_preferences import TypeCheckPreferencesDialog
from .typecheck_worker import TypeCheckSignals, TypeCheckTask
from .theme import apply_theme
from .conventions import category_sort_key, display_scope, is_special_category

# PySide6 exposes ExtraSelection through QTextEdit, not QPlainTextEdit.
from PySide6.QtWidgets import QTextEdit
QPlainTextEditExtraSelection = QTextEdit.ExtraSelection

class MainWindow(QMainWindow):
    def __init__(self, path=None, workspace=None):
        super().__init__()
        self.doc = None
        self.workspace = workspace or Workspace()
        self.workspace.register(self)
        self.workspace.file_changed.connect(self._workspace_file_changed)
        self.world: World | None = self.workspace.world
        self.child_windows = []
        self.module_entries: dict[str, ModuleEntry] = {}
        self.settings = QSettings("PyBrowser", "PyBrowser")
        self.thread_pool = QThreadPool.globalInstance()
        self.index_cache = ModuleIndexCache()
        self.index_generation = 0
        self.index_cancelled = Event()
        self.index_signals = IndexSignals()
        self.index_signals.result.connect(self._index_result)
        self.index_signals.progress.connect(self._index_progress)
        self.index_signals.finished.connect(self._index_finished)
        self.typecheck_signals = TypeCheckSignals()
        self.typecheck_signals.finished.connect(self._typecheck_finished)
        self.typecheck_running = False
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(250)
        self.refresh_timer.timeout.connect(self._refresh_world)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self._world_changed)
        self.watcher.fileChanged.connect(self._file_changed)
        self.scope = None
        self.member = None
        self.loading = False
        self.history = NavigationHistory()
        self.navigating_history = False
        self.search_matches: tuple[SearchMatch, ...] = ()
        self.search_index = -1
        self.search_source = ""
        self.replace_dialog = None
        self.resize(1400, 900)
        self.setWindowTitle("PyBrowser")
        self._ui()
        self._actions()
        self._restore_window_state()
        self._apply_editor_preferences()
        if path:
            self.open(path)

    def focusInEvent(self, event):
        self.workspace.active_browser = self
        super().focusInEvent(event)

    def _ui(self):
        self.modules = QTreeWidget()
        self.modules.setHeaderHidden(True)
        self.modules.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.modules.customContextMenuRequested.connect(self._modules_context_menu)
        self.scopes = QListWidget()
        self.scopes.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.scopes.customContextMenuRequested.connect(self._scopes_context_menu)
        self.categories = CategoryListWidget()
        self.categories.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.categories.customContextMenuRequested.connect(self._categories_context_menu)
        self.categories.member_dropped.connect(self._member_dropped)
        self.members = MemberListWidget()
        self.members.setItemDelegate(MemberDelegate(self.members))
        self.members.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.members.customContextMenuRequested.connect(self._members_context_menu)
        top = QSplitter(Qt.Orientation.Horizontal)
        for title, widget in (("Modules", self.modules), ("Scopes", self.scopes), ("Categories", self.categories), ("Members", self.members)):
            box = QWidget()
            layout = QVBoxLayout(box)
            layout.setContentsMargins(3, 3, 3, 3)
            label = QLabel(title)
            label.setStyleSheet("font-weight:bold")
            layout.addWidget(label)
            layout.addWidget(widget)
            top.addWidget(box)
        self.modules.currentItemChanged.connect(self._module)
        self.scopes.currentRowChanged.connect(self._scope)
        self.categories.currentTextChanged.connect(self._category)
        self.members.currentRowChanged.connect(self._member)

        self.find_text = QLineEdit()
        self.find_text.setPlaceholderText("Find text")
        self.find_text.setClearButtonEnabled(True)
        self.find_text.returnPressed.connect(self.execute_find)
        self.find_text.textChanged.connect(self._search_text_changed)
        self.current_entity_only = QCheckBox("Current method/entity only")
        self.current_entity_only.setChecked(True)
        self.current_entity_only.toggled.connect(self._search_scope_changed)
        self.match_indicator = QLabel("0 matches")
        self.match_indicator.setMinimumWidth(90)
        find_bar = QWidget()
        find_layout = QHBoxLayout(find_bar)
        find_layout.setContentsMargins(6, 4, 6, 4)
        find_layout.addWidget(QLabel("Find:"))
        find_layout.addWidget(self.find_text, 1)
        find_layout.addWidget(self.current_entity_only)
        find_layout.addWidget(self.match_indicator)

        self.crumb = QLabel("Open a Python file to begin")
        self.editor = Editor()
        self.editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.editor.customContextMenuRequested.connect(self._editor_context_menu)
        self.editor.textChanged.connect(self._modified)
        self.editor.browse_class_requested.connect(self.open_browser_on_class)

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(4, 0, 4, 4)
        lower_layout.addWidget(find_bar)
        lower_layout.addWidget(self.crumb)
        lower_layout.addWidget(self.editor)
        main = QSplitter(Qt.Orientation.Vertical)
        self.diagnostics = DiagnosticsPanel()
        self.diagnostics.activated.connect(self._navigate_diagnostic)
        self.diagnostics.setVisible(False)
        main.addWidget(top)
        main.addWidget(lower)
        main.addWidget(self.diagnostics)
        main.setSizes([280, 620, 0])
        self.setCentralWidget(main)
        self.setStatusBar(QStatusBar())

    def _actions(self):
        open_action = QAction("Open Python File...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.choose)
        folder_action = QAction("Open Folder...", self)
        folder_action.setShortcut("Ctrl+Shift+O")
        folder_action.triggered.connect(self.choose_folder)
        save_action = QAction("Save Member", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save)
        find_action = QAction("Find", self)
        find_action.setShortcut(QKeySequence.StandardKey.Find)
        find_action.triggered.connect(self.focus_find)
        next_action = QAction("Find Next", self)
        next_action.setShortcut("Ctrl+G")
        next_action.triggered.connect(self.find_next)
        replace_action = QAction("Replace in Current Entity", self)
        replace_action.setShortcut("Ctrl+H")
        replace_action.triggered.connect(self.show_replace_dialog)
        comment_action = QAction("Toggle Comment", self)
        comment_action.setShortcut("Ctrl+/")
        comment_action.triggered.connect(self.editor.toggle_comment)
        preferences_action = QAction("Preferences...", self)
        preferences_action.triggered.connect(self.show_preferences)
        typecheck_action = QAction("Run Type Check", self)
        typecheck_action.setShortcut("Ctrl+Shift+T")
        typecheck_action.triggered.connect(self.run_type_check)
        toggle_diagnostics_action = QAction("Show Diagnostics", self)
        toggle_diagnostics_action.setCheckable(True)
        toggle_diagnostics_action.toggled.connect(self.diagnostics.setVisible)
        typecheck_settings_action = QAction("Type Checker Settings...", self)
        typecheck_settings_action.triggered.connect(self.show_typecheck_settings)
        new_browser_action = QAction("New Browser", self)
        new_browser_action.setShortcut("Ctrl+Shift+B")
        new_browser_action.triggered.connect(self.new_browser)
        abandon_action = QAction("Abandon Entity Changes", self)
        abandon_action.setShortcut("Ctrl+L")
        abandon_action.triggered.connect(self.abandon_changes)
        quick_module_action = QAction("Quick Open Module", self)
        quick_module_action.setShortcut("Ctrl+P")
        quick_module_action.triggered.connect(self.quick_open_module)
        quick_symbol_action = QAction("Quick Open Symbol", self)
        quick_symbol_action.setShortcut("Ctrl+T")
        quick_symbol_action.triggered.connect(self.quick_open_symbol)
        project_find_action = QAction("Find in World", self)
        project_find_action.setShortcut("Ctrl+Shift+F")
        project_find_action.triggered.connect(self.find_in_world)
        back_action = QAction("Back", self)
        back_action.setShortcut("Alt+Left")
        back_action.triggered.connect(self.navigate_back)
        forward_action = QAction("Forward", self)
        forward_action.setShortcut("Alt+Right")
        forward_action.triggered.connect(self.navigate_forward)
        goto_action = QAction("Go to Line", self)
        goto_action.setShortcut("Ctrl+Alt+G")
        goto_action.triggered.connect(self.go_to_line)
        focus_crumb_action = QAction("Focus Location", self)
        focus_crumb_action.setShortcut("Ctrl+Alt+L")
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([open_action, folder_action, save_action])
        self.recent_menu = file_menu.addMenu("Recent Worlds")
        self._rebuild_recent_menu()
        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addActions([find_action, next_action, replace_action, project_find_action, comment_action])
        edit_menu.addSeparator()
        edit_menu.addAction(abandon_action)
        edit_menu.addSeparator()
        edit_menu.addAction(preferences_action)
        tools_menu = self.menuBar().addMenu("&Tools")
        tools_menu.addAction(new_browser_action)
        tools_menu.addSeparator()
        tools_menu.addAction(typecheck_action)
        tools_menu.addAction(toggle_diagnostics_action)
        tools_menu.addSeparator()
        tools_menu.addAction(typecheck_settings_action)
        structure_menu = self.menuBar().addMenu("&Structure")
        commands = [
            ("New Function...", self.new_function), ("New Class...", self.new_class),
            ("New Method...", self.new_method),
            ("Rename Category...", self.rename_current_category),
            ("Move Entity to Category...", self.move_current_member),
            ("Duplicate Entity", self.duplicate_current_member),
            ("Delete Entity...", self.delete_current_member),
        ]
        for title, callback in commands:
            action = structure_menu.addAction(title)
            action.triggered.connect(callback)
        kind_menu = structure_menu.addMenu("Convert Method Kind")
        for title, kind in (("Instance Method", "instance"), ("Static Method", "static"), ("Class Method", "class"), ("Property", "property")):
            action = kind_menu.addAction(title)
            action.triggered.connect(lambda checked=False, value=kind: self.convert_current_method(value))
        structure_menu.addSeparator()
        init_action = structure_menu.addAction("Create Package __init__.py")
        init_action.triggered.connect(self.create_init_file)
        navigate_menu = self.menuBar().addMenu("&Navigate")
        navigate_menu.addActions([quick_module_action, quick_symbol_action, back_action, forward_action, goto_action])
        self.addActions([open_action, save_action, find_action, next_action, replace_action, abandon_action, new_browser_action, typecheck_action, quick_module_action, quick_symbol_action, project_find_action, back_action, forward_action, goto_action])

    def _typecheck_preferences(self):
        return {
            "checker": self.settings.value("typecheck/checker", "auto", str),
            "executable": self.settings.value("typecheck/executable", "", str),
            "python_path": self.settings.value("typecheck/pythonPath", "", str),
        }

    def show_typecheck_settings(self):
        dialog = TypeCheckPreferencesDialog(self._typecheck_preferences(), self)
        if dialog.exec():
            values = dialog.values()
            self.settings.setValue("typecheck/checker", values["checker"])
            self.settings.setValue("typecheck/executable", values["executable"])
            self.settings.setValue("typecheck/pythonPath", values["python_path"])

    def run_type_check(self):
        if self.typecheck_running:
            self.statusBar().showMessage("Type checking is already running", 3000)
            return
        if not self.world:
            QMessageBox.information(self, "Type Check", "Open a Python file or directory world first.")
            return
        if self.editor.document().isModified():
            QMessageBox.information(self, "Type Check", "Save or abandon the current entity changes before type checking.")
            return
        values = self._typecheck_preferences()
        target = self.world.modules[0].path if self.world.single_file else self.world.root
        task = TypeCheckTask(target, values["checker"], values["executable"], values["python_path"], self.typecheck_signals)
        self.typecheck_running = True
        self.diagnostics.setVisible(True)
        self.diagnostics.summary.setText("Type checking in background...")
        self.statusBar().showMessage("Running type checker...")
        self.thread_pool.start(task)

    def _typecheck_finished(self, result):
        self.typecheck_running = False
        self.diagnostics.set_result(result)
        self.diagnostics.setVisible(True)
        if result.fatal_error:
            self.statusBar().showMessage(f"Type checker failed: {result.fatal_error}", 8000)
        else:
            self.statusBar().showMessage(f"Type check complete: {result.error_count} error(s), {result.warning_count} warning(s)", 8000)

    def _navigate_diagnostic(self, diagnostic):
        if self.editor.document().isModified() and not self._confirm_discard():
            return
        path = diagnostic.file.resolve()
        if not path.exists():
            self.statusBar().showMessage(f"Diagnostic file no longer exists: {path}", 5000)
            return
        self._select_module_path(path)
        self._select_line_result(diagnostic.line, diagnostic.column)

    def _preferences(self):
        return {
            "font_family": self.settings.value("editor/fontFamily", "0xProto Nerd Font", str),
            "font_size": self.settings.value("editor/fontSize", 11, int),
            "tab_width": self.settings.value("editor/tabWidth", 4, int),
            "show_whitespace": self.settings.value("editor/showWhitespace", False, bool),
            "theme": self.settings.value("appearance/theme", "dark", str),
        }

    def _apply_editor_preferences(self):
        values = self._preferences()
        font = QFont(values["font_family"], values["font_size"])
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        for editor in self.findChildren(Editor):
            editor.setFont(font)
            editor.set_tab_width(values["tab_width"])
            editor.set_show_whitespace(values["show_whitespace"])
        apply_theme(self.window().windowHandle().screen().context().application() if False else __import__("PySide6.QtWidgets", fromlist=["QApplication"]).QApplication.instance(), values["theme"])

    def show_preferences(self):
        dialog = PreferencesDialog(self._preferences(), self)
        if not dialog.exec():
            return
        values = dialog.values()
        self.settings.setValue("editor/fontFamily", values["font_family"])
        self.settings.setValue("editor/fontSize", values["font_size"])
        self.settings.setValue("editor/tabWidth", values["tab_width"])
        self.settings.setValue("editor/showWhitespace", values["show_whitespace"])
        self.settings.setValue("appearance/theme", values["theme"])
        self._apply_editor_preferences()

    def show_replace_dialog(self):
        selected = self.editor.textCursor().selectedText()
        self.replace_dialog = ReplaceDialog(self, selected)
        self.replace_dialog.replace_one.connect(self._replace_one)
        self.replace_dialog.replace_all.connect(self._replace_all)
        self.replace_dialog.show()

    def _replace_one(self, find_text, replacement_text, case_sensitive):
        if not find_text:
            return
        source = self.editor.toPlainText()
        cursor = self.editor.textCursor()
        start = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        haystack = source if case_sensitive else source.casefold()
        needle = find_text if case_sensitive else find_text.casefold()
        position = haystack.find(needle, start)
        if position < 0:
            position = haystack.find(needle, 0, start)
        if position < 0:
            self.replace_dialog.status.setText("No matches")
            return
        cursor.setPosition(position)
        cursor.setPosition(position + len(find_text), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement_text)
        self.editor.setTextCursor(cursor)
        self.replace_dialog.status.setText("Replaced one match")

    def _replace_all(self, find_text, replacement_text, case_sensitive):
        if not find_text:
            return
        source = self.editor.toPlainText()
        if case_sensitive:
            count = source.count(find_text)
            result = source.replace(find_text, replacement_text)
        else:
            result, count = __import__("re").subn(__import__("re").escape(find_text), lambda _m: replacement_text, source, flags=__import__("re").IGNORECASE)
        if count:
            cursor = self.editor.textCursor()
            cursor.beginEditBlock()
            self.editor.setPlainText(result)
            cursor.endEditBlock()
            self.editor.document().setModified(True)
        self.replace_dialog.status.setText(f"Replaced {count} match(es)")

    def _restore_window_state(self):
        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def focus_find(self):
        self.find_text.setFocus()
        self.find_text.selectAll()

    def _search_text_changed(self):
        self._clear_search_highlights()
        self.search_matches = ()
        self.search_index = -1
        self.search_source = ""
        self.replace_dialog = None
        self._update_match_indicator()

    def _search_scope_changed(self):
        if self.find_text.text():
            self.execute_find()

    def execute_find(self):
        query = self.find_text.text()
        if not query:
            self._search_text_changed()
            return
        if self.current_entity_only.isChecked():
            source = self.editor.toPlainText()
            self.search_matches = find_all(source, query)
            self.search_source = "entity"
        elif self.doc:
            source = self._candidate_document_text()
            self.search_matches = find_all(source, query)
            self.search_source = "file"
        else:
            self.search_matches = ()
            self.search_source = ""
        self.replace_dialog = None
        self.search_index = 0 if self.search_matches else -1
        self._show_search_match()

    def find_next(self):
        query = self.find_text.text()
        if not query:
            self.focus_find()
            return
        expected_source = "entity" if self.current_entity_only.isChecked() else "file"
        if not self.search_matches or self.search_source != expected_source:
            self.execute_find()
            return
        self.search_index = (self.search_index + 1) % len(self.search_matches)
        self._show_search_match()

    def _candidate_document_text(self):
        if self.doc and self.member and self.editor.document().isModified():
            return replacement(self.doc, self.member, self.editor.toPlainText())
        return self.doc.text if self.doc else ""

    def _show_search_match(self):
        if self.search_index < 0 or not self.search_matches:
            self._clear_search_highlights()
            self._update_match_indicator()
            return
        match = self.search_matches[self.search_index]
        if self.search_source == "file":
            member = self._member_for_file_offset(match.start)
            if member is None:
                self.statusBar().showMessage("Match is inside a class declaration not exposed as an editable entity", 5000)
                self._update_match_indicator()
                return
            if member != self.member:
                if self.editor.document().isModified() and not self._confirm_discard():
                    return
                self._select_browser_member(member)
            local_start = match.start - member.span.start
            local_end = match.end - member.span.start
        else:
            local_start, local_end = match.start, match.end
        self._select_editor_range(local_start, local_end)
        self._update_match_indicator()

    def _member_for_file_offset(self, offset):
        candidates = []
        for scope in self.doc.scopes:
            for member in scope.members:
                if not member.synthetic and member.span.start <= offset < member.span.end:
                    candidates.append(member)
        return min(candidates, key=lambda item: item.span.end - item.span.start) if candidates else None

    def _select_browser_member(self, target):
        self.loading = True
        try:
            for index, scope in enumerate(self.doc.scopes):
                if scope.name == target.scope:
                    self.scopes.setCurrentRow(index)
                    self.scope = scope
                    break
            found = self.categories.findItems(target.category, Qt.MatchFlag.MatchExactly)
            if found:
                self.categories.setCurrentItem(found[0])
            visible = self._visible()
            for index, member in enumerate(visible):
                if member == target:
                    self.members.setCurrentRow(index)
                    self.member = member
                    self._load_member(member)
                    break
        finally:
            self.loading = False

    def _select_editor_range(self, start, end):
        cursor = self.editor.textCursor()
        cursor.setPosition(max(0, start))
        cursor.setPosition(max(start, end), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()
        self.editor.setFocus()
        selection = QPlainTextEditExtraSelection()
        selection.cursor = cursor
        selection.format.setBackground(QColor("#7a5f00"))
        selection.format.setForeground(QColor("#ffffff"))
        self.editor.setExtraSelections([selection])

    def _clear_search_highlights(self):
        self.editor.setExtraSelections([])

    def _update_match_indicator(self):
        count = len(self.search_matches)
        if count and self.search_index >= 0:
            self.match_indicator.setText(f"{self.search_index + 1}/{count} matches")
        else:
            self.match_indicator.setText("0 matches")

    def _modified(self):
        if self.loading:
            return
        modified = self.editor.document().isModified()
        self.setWindowModified(modified)
        self._update_modified_indicator(modified)
        if self.find_text.text() and self.current_entity_only.isChecked():
            self.execute_find()
        elif self.search_source:
            self._search_text_changed()

    def _confirm_discard(self):
        if not self.editor.document().isModified():
            return True
        name = self.member.label if self.member else "this entity"
        answer = QMessageBox.question(
            self,
            "Abandon unsaved changes?",
            f"Do you want to abandon changes to {name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.abandon_changes()
            return True
        self._restore_current_browser_selection()
        self.editor.setFocus()
        self.statusBar().showMessage("Navigation cancelled; unsaved changes remain in the current entity", 4000)
        return False

    def abandon_changes(self):
        """Restore the selected entity from the last parsed on-disk document."""
        if not self.doc or not self.member or not self.editor.document().isModified():
            self.statusBar().showMessage("No entity changes to abandon", 3000)
            return
        cursor_position = self.editor.textCursor().position()
        self.loading = True
        try:
            self.editor.setPlainText(self.doc.source(self.member))
            self.editor.document().setModified(False)
            cursor = self.editor.textCursor()
            cursor.setPosition(min(cursor_position, len(self.editor.toPlainText())))
            self.editor.setTextCursor(cursor)
        finally:
            self.loading = False
        self.setWindowModified(False)
        self._update_modified_indicator(False)
        self._search_text_changed()
        self.statusBar().showMessage(f"Abandoned changes to {self.member.label}", 4000)

    def _update_modified_indicator(self, modified):
        item = self.members.currentItem()
        if item is None:
            return
        item.setForeground(QColor("#ffd166") if modified else QColor("#e6e6e6"))
        font = item.font()
        font.setBold(modified)
        item.setFont(font)
        base = self.member.tooltip or self.member.label if self.member else item.text()
        item.setToolTip(("Unsaved changes\n" + base) if modified else base)

    def _restore_current_browser_selection(self):
        """Atomically restore all four browser panes without reloading editor text.

        Selection-change signals fire after Qt has already moved the visual selection.
        Rebuild the dependent panes under signal blockers so answering No can never
        leave the browser on a different scope, category, or entity.
        """
        if not self.doc or not self.member:
            return
        target = self.member
        self.loading = True
        try:
            # Restore the module tree selection.
            target_path = str(self.doc.path.resolve())
            queue = [self.modules.topLevelItem(i) for i in range(self.modules.topLevelItemCount())]
            while queue:
                item = queue.pop(0)
                if item.data(0, Qt.ItemDataRole.UserRole) == target_path:
                    blocker = QSignalBlocker(self.modules)
                    self.modules.setCurrentItem(item)
                    del blocker
                    break
                queue.extend(item.child(i) for i in range(item.childCount()))

            # Restore scope and rebuild its categories from the document model.
            scope_index = next((i for i, scope in enumerate(self.doc.scopes) if scope.name == target.scope), -1)
            if scope_index < 0:
                return
            self.scope = self.doc.scopes[scope_index]
            blocker = QSignalBlocker(self.scopes)
            self.scopes.setCurrentRow(scope_index)
            del blocker

            categories = sorted(
                dict.fromkeys(item.category for item in self.scope.members),
                key=category_sort_key,
            )
            blocker = QSignalBlocker(self.categories)
            self.categories.clear()
            self.categories.addItems(categories)
            category_index = categories.index(target.category) if target.category in categories else -1
            self.categories.setCurrentRow(category_index)
            del blocker

            # Rebuild members for the restored category and select the exact entity.
            visible = [item for item in self.scope.members if item.category == target.category]
            blocker = QSignalBlocker(self.members)
            self.members.clear()
            member_index = -1
            for index, member in enumerate(visible):
                self.members.addItem(member.label)
                list_item = self.members.item(self.members.count() - 1)
                list_item.setToolTip(member.tooltip or member.label)
                if member == target:
                    member_index = index
            self.members.setCurrentRow(member_index)
            del blocker
            self.member = target
            self._update_modified_indicator(True)
        finally:
            self.loading = False

    def choose(self):
        name, _ = QFileDialog.getOpenFileName(self, "Open Python File", "", "Python files (*.py)")
        if name and self._confirm_discard():
            self.open_world_path(Path(name))

    def choose_folder(self):
        name = QFileDialog.getExistingDirectory(self, "Open Python Project Folder")
        if name and self._confirm_discard():
            self.open_world_path(Path(name))

    def open(self, path, restore=None):
        path = Path(path)
        if path.is_dir() or self.world is None or path not in [item.path for item in self.world.modules]:
            self.open_world_path(path, restore)
        else:
            self._open_module(path, restore)

    def open_world_path(self, path, restore=None):
        try:
            world = open_world(Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "Cannot open world", str(exc))
            return
        self.world = world
        self.workspace.set_world(world)
        self.doc = None
        self.scope = None
        self.member = None
        self._populate_module_tree()
        self._watch_world()
        self._start_background_index()
        self._remember_world(world.root if not world.single_file else world.modules[0].path)
        title = world.modules[0].path.name if world.single_file else world.root.name
        self.setWindowTitle(title + "[*] - PyBrowser")
        self.statusBar().showMessage(f"Opened {len(world.modules)} Python module(s)", 5000)
        if restore and isinstance(restore, tuple) and len(restore) == 4:
            module_path, scope, category, label = restore
            self._select_module_path(Path(module_path), (scope, category, label))
        elif world.modules:
            self._select_module_path(world.modules[0].path)

    def _open_module(self, path, restore=None):
        try:
            self.doc = read_document(Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "Cannot open module", str(exc))
            return
        self.loading = True
        self.scopes.clear()
        self.scopes.addItems([display_scope(item.name) for item in self.doc.scopes])
        self.loading = False
        if self.scopes.count():
            self.scopes.setCurrentRow(0)
        self._search_text_changed()
        self._watch_current_file()
        if restore:
            self._restore(*restore)

    def _populate_module_tree(self):
        self.loading = True
        self.modules.clear()
        self.module_entries.clear()
        nodes = {}
        for entry in self.world.modules:
            parent = self.modules.invisibleRootItem()
            accumulated = []
            parts = entry.relative_path.parts
            for part in parts[:-1]:
                accumulated.append(part)
                key = "/".join(accumulated)
                if key not in nodes:
                    node = QTreeWidgetItem([part])
                    node.setData(0, Qt.ItemDataRole.UserRole, None)
                    parent.addChild(node)
                    nodes[key] = node
                parent = nodes[key]
            leaf = QTreeWidgetItem([parts[-1]])
            key = str(entry.path)
            leaf.setData(0, Qt.ItemDataRole.UserRole, key)
            cached = self.index_cache.get(entry.path)
            if cached and cached.error:
                leaf.setText(0, parts[-1] + "  [parse error]")
                leaf.setToolTip(0, entry.dotted_name + "\n" + cached.error)
                leaf.setForeground(0, QColor("#e06c75"))
            elif cached:
                symbol_count = sum(len(scope.members) for scope in cached.scopes or ())
                leaf.setToolTip(0, f"{entry.dotted_name}\n{len(cached.scopes or ())} scope(s), {symbol_count} browser item(s)")
            else:
                leaf.setToolTip(0, entry.dotted_name + "\nPending background index")
            parent.addChild(leaf)
            self.module_entries[key] = entry
        self.modules.expandAll()
        self.loading = False

    def _module(self, current, previous=None):
        if self.loading or current is None:
            return
        key = current.data(0, Qt.ItemDataRole.UserRole)
        if not key:
            return
        if self.editor.document().isModified() and not self._confirm_discard():
            return
        self._open_module(Path(key))

    def _select_module_path(self, path, restore=None):
        target = str(Path(path).resolve())
        iterator = [self.modules.topLevelItem(i) for i in range(self.modules.topLevelItemCount())]
        while iterator:
            item = iterator.pop(0)
            if item.data(0, Qt.ItemDataRole.UserRole) == target:
                self.modules.setCurrentItem(item)
                if restore:
                    self._open_module(Path(target), restore)
                return
            iterator[0:0] = [item.child(i) for i in range(item.childCount())]

    def _watch_world(self):
        existing = self.watcher.directories() + self.watcher.files()
        if existing:
            self.watcher.removePaths(existing)
        if self.world and not self.world.single_file:
            directories = {str(self.world.root)}
            directories.update(str(item.path.parent) for item in self.world.modules)
            self.watcher.addPaths(sorted(directories))
        self._watch_current_file()

    def _watch_current_file(self):
        if self.doc and str(self.doc.path) not in self.watcher.files():
            self.watcher.addPath(str(self.doc.path))

    def _world_changed(self, _path):
        if self.world and not self.world.single_file:
            self.refresh_timer.start()

    def _refresh_world(self):
        if not self.world or self.world.single_file:
            return
        current = self.doc.path if self.doc else None
        try:
            self.world = open_world(self.world.root)
            self.index_cache.retain({entry.path for entry in self.world.modules})
            self._populate_module_tree()
            self._watch_world()
            self._start_background_index()
            if current and current.exists():
                self._select_module_path(current)
        except OSError as exc:
            self.statusBar().showMessage(str(exc), 5000)

    def _file_changed(self, path):
        if self.doc and Path(path) == self.doc.path and not self.editor.document().isModified():
            self.statusBar().showMessage("Current module changed outside PyBrowser; reloading", 5000)
            location = (self.member.scope, self.member.category, self.member.label) if self.member else None
            self._open_module(self.doc.path, location)

    def _start_background_index(self):
        self.index_cancelled.set()
        self.index_cancelled = Event()
        self.index_generation += 1
        generation = self.index_generation
        modules = tuple(entry for entry in self.world.modules if self.index_cache.get(entry.path) is None)
        if not modules:
            self.statusBar().showMessage(f"World ready: {len(self.world.modules)} module(s)", 4000)
            return
        task = IndexWorldTask(modules, generation, self.index_signals, self.index_cancelled)
        self.thread_pool.start(task)
        self.statusBar().showMessage(f"Indexing 0/{len(modules)} modules...")

    def _index_result(self, result: ModuleIndexResult):
        if result.generation != self.index_generation:
            return
        self.index_cache.put(result.path, result.scopes, result.error)
        self._update_module_tree_item(result.path)

    def _index_progress(self, generation, completed, total):
        if generation == self.index_generation:
            self.statusBar().showMessage(f"Indexing {completed}/{total} modules...")

    def _index_finished(self, generation):
        if generation != self.index_generation:
            return
        errors = sum(1 for entry in self.world.modules if (cached := self.index_cache.get(entry.path)) and cached.error)
        suffix = f", {errors} parse error(s)" if errors else ""
        self.statusBar().showMessage(f"Indexed {len(self.world.modules)} modules{suffix}", 6000)

    def _update_module_tree_item(self, path):
        target = str(Path(path).resolve())
        queue = [self.modules.topLevelItem(i) for i in range(self.modules.topLevelItemCount())]
        while queue:
            item = queue.pop(0)
            if item.data(0, Qt.ItemDataRole.UserRole) == target:
                entry = self.module_entries.get(target)
                cached = self.index_cache.get(Path(target))
                if entry and cached:
                    item.setText(0, entry.relative_path.name + ("  [parse error]" if cached.error else ""))
                    if cached.error:
                        item.setForeground(0, QColor("#e06c75"))
                        item.setToolTip(0, entry.dotted_name + "\n" + cached.error)
                    else:
                        item.setForeground(0, QColor("#e6e6e6"))
                        count = sum(len(scope.members) for scope in cached.scopes or ())
                        item.setToolTip(0, f"{entry.dotted_name}\n{len(cached.scopes or ())} scope(s), {count} browser item(s)")
                return
            queue.extend(item.child(i) for i in range(item.childCount()))

    def _recent_worlds(self):
        return [value for value in self.settings.value("recentWorlds", [], list) if Path(value).exists()]

    def _remember_world(self, path):
        value = str(Path(path).resolve())
        recent = [item for item in self._recent_worlds() if item != value]
        self.settings.setValue("recentWorlds", [value, *recent][:10])
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        if not hasattr(self, "recent_menu"):
            return
        self.recent_menu.clear()
        recent = self._recent_worlds()
        self.recent_menu.setEnabled(bool(recent))
        for value in recent:
            action = self.recent_menu.addAction(value)
            action.triggered.connect(lambda checked=False, p=value: self.open_world_path(Path(p)))

    def _scope(self, row):
        if row < 0 or not self.doc:
            return
        if self.member and not self.loading and not self._confirm_discard():
            return
        self.scope = self.doc.scopes[row]
        self.categories.clear()
        self.categories.addItems(sorted(dict.fromkeys(item.category for item in self.scope.members), key=category_sort_key))
        if self.categories.count():
            self.categories.setCurrentRow(0)

    def _category(self, category):
        if self.member and not self.loading and self.editor.document().isModified() and not self._confirm_discard():
            return
        self.members.clear()
        if self.scope:
            for member in (item for item in self.scope.members if item.category == category):
                self.members.addItem(member.label)
                self.members.item(self.members.count() - 1).setToolTip(member.tooltip or member.label)
        if self.members.count():
            self.members.setCurrentRow(0)

    def _visible(self):
        category = self.categories.currentItem().text() if self.categories.currentItem() else ""
        return [item for item in self.scope.members if item.category == category] if self.scope else []

    def _member(self, row):
        items = self._visible()
        new = items[row] if 0 <= row < len(items) else None
        if self.member and new != self.member and not self.loading and self.editor.document().isModified() and not self._confirm_discard():
            return
        self.member = new
        self._load_member(new)

    def _load_member(self, member):
        self.loading = True
        if member:
            self.editor.setPlainText(self.doc.source(member))
            self.editor.document().setModified(False)
            self.crumb.setText(f"{self.doc.path.name} > {display_scope(member.scope)} > {member.category} > {member.label}")
        else:
            self.editor.clear()
        self.loading = False
        self.setWindowModified(False)
        self._update_modified_indicator(False)
        if self.find_text.text() and self.current_entity_only.isChecked():
            self.execute_find()
        if member and not self.navigating_history:
            self.history.visit(self._current_location())

    def _current_location(self):
        if not self.doc or not self.member:
            return None
        return Location(self.doc.path, self.member.scope, self.member.category, self.member.label, self.editor.textCursor().position())

    def quick_open_module(self):
        if not self.world:
            return
        class ModuleChoice:
            def __init__(self, entry): self.entry = entry; self.display = f"{entry.dotted_name}  |  {entry.relative_path}"
        dialog = QuickDialog("Quick Open Module", [ModuleChoice(entry) for entry in self.world.modules], self)
        if dialog.exec():
            choice = dialog.selected_entry()
            if choice and self._confirm_discard(): self._select_module_path(choice.entry.path)

    def _world_symbols(self):
        values = []
        if not self.world:
            return values
        for entry in self.world.modules:
            cached = self.index_cache.get(entry.path)
            if cached and cached.scopes:
                values.extend(symbols_for_module(entry.path, entry.dotted_name, cached.scopes))
        return values

    def quick_open_symbol(self):
        dialog = QuickDialog("Quick Open Class, Method, or Function", self._world_symbols(), self)
        if dialog.exec():
            entry = dialog.selected_entry()
            if entry: self._navigate_symbol(entry)

    def _navigate_symbol(self, entry):
        if not self._confirm_discard():
            return
        self._select_module_path(entry.module, (entry.scope, entry.category, entry.label))

    def find_in_world(self):
        if not self.world:
            return
        query, ok = QInputDialog.getText(self, "Find in World", "Search text:")
        if not ok or not query:
            return
        results = []
        for entry in self.world.modules:
            try: results.extend(search_file(entry.path, entry.dotted_name, query))
            except (OSError, UnicodeError): pass
        dialog = QuickDialog(f"Find in World: {query} ({len(results)} matches)", results, self)
        if dialog.exec():
            result = dialog.selected_entry()
            if result and self._confirm_discard():
                self._select_module_path(result.module)
                self._select_line_result(result.line, result.column, query)

    def _select_line_result(self, line, column=1, query=None):
        if not self.doc:
            return
        offset = 0
        lines = self.doc.text.splitlines(keepends=True)
        offset = sum(len(value) for value in lines[:max(0, line - 1)]) + max(0, column - 1)
        member = self._member_for_file_offset(offset)
        if member:
            self._select_browser_member(member)
            local = offset - member.span.start
            end = local + len(query or "")
            self._select_editor_range(local, end if end > local else local)

    def navigate_back(self):
        self._navigate_history_location(self.history.back())

    def navigate_forward(self):
        self._navigate_history_location(self.history.forward())

    def _navigate_history_location(self, location):
        if not location or not self._confirm_discard():
            return
        self.navigating_history = True
        try:
            self._select_module_path(location.module, (location.scope, location.category, location.member_label))
            cursor = self.editor.textCursor()
            cursor.setPosition(min(location.cursor_offset, len(self.editor.toPlainText())))
            self.editor.setTextCursor(cursor)
        finally:
            self.navigating_history = False

    def go_to_line(self):
        if not self.doc:
            return
        line, ok = QInputDialog.getInt(self, "Go to Line", "Line number:", 1, 1, max(1, len(self.doc.text.splitlines())))
        if ok: self._select_line_result(line)

    def _callable_name_at_cursor(self):
        cursor = self.editor.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        value = cursor.selectedText().strip()
        if value and value.isidentifier():
            return value
        return callable_name_from_label(self.member.label) if self.member else ""

    def _view_in_file(self, line=1):
        if not self.doc:
            return
        window = FileViewWindow(self.doc.path, self.workspace, line, self)
        window.show()
        self.child_windows.append(window)

    def _modules_context_menu(self, position):
        item = self.modules.itemAt(position)
        if item is None:
            return
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if not key:
            return
        menu = QMenu(self)
        menu.addAction("View in file...", lambda: self._open_file_view_path(Path(key), 1))
        menu.exec(self.modules.viewport().mapToGlobal(position))

    def _open_file_view_path(self, path, line=1):
        window = FileViewWindow(path, self.workspace, line, self)
        window.show()
        self.child_windows.append(window)

    def _scopes_context_menu(self, position):
        item = self.scopes.itemAt(position)
        if item is None:
            return
        self.scopes.setCurrentItem(item)
        menu = QMenu(self)
        line = 1
        if self.scope and self.scope.members:
            line = min(member.span.first for member in self.scope.members)
        menu.addAction("View in file...", lambda: self._view_in_file(line))
        menu.addSeparator()
        menu.addAction("New Class...", self.new_class)
        menu.exec(self.scopes.viewport().mapToGlobal(position))

    def _member_dropped(self, row, category):
        visible = self._visible()
        if not (0 <= row < len(visible)):
            return
        member = visible[row]
        if member.synthetic or member.category == category:
            return
        try:
            self._apply_structural_edit(move_member(self.doc, member, category), f"Moved {member.label} to {category}")
        except StructuralEditError as exc:
            QMessageBox.warning(self, "Cannot move entity", str(exc))

    def new_browser(self):
        if not self.world:
            return
        window = MainWindow(workspace=self.workspace)
        window.open_world_path(self.world.modules[0].path if self.world.single_file else self.world.root)
        if self.doc and self.member:
            window._select_module_path(self.doc.path, (self.member.scope, self.member.category, self.member.label))
        window.show()
        self.child_windows.append(window)

    def open_browser_on_class(self, class_name):
        if not self.world:
            return
        matches = []
        for entry in self.world.modules:
            cached = self.index_cache.get(entry.path)
            scopes = cached.scopes if cached and cached.scopes else ()
            for scope in scopes:
                if scope.name.split(".")[-1] == class_name:
                    matches.append((entry.path, scope.name))
        if not matches:
            self.statusBar().showMessage(f"Class {class_name} was not found in the indexed world", 5000)
            return
        path, scope = matches[0]
        window = MainWindow(workspace=self.workspace)
        window.open_world_path(self.world.modules[0].path if self.world.single_file else self.world.root)
        window._select_module_path(path)
        for index, item in enumerate(window.doc.scopes):
            if item.name == scope:
                window.scopes.setCurrentRow(index)
                break
        window.show()
        self.child_windows.append(window)

    def _workspace_file_changed(self, path, origin):
        if origin is self or not self.doc or Path(path) != self.doc.path:
            return
        if self.editor.document().isModified():
            self.statusBar().showMessage("File changed in another workspace window; save is blocked until you reload", 7000)
            return
        location = (self.member.scope, self.member.category, self.member.label) if self.member else None
        self.index_cache.put(self.doc.path, None)
        self._open_module(self.doc.path, location)

    def _members_context_menu(self, position):
        member = self.member
        if not member:
            return
        menu = QMenu(self)
        menu.addAction("View in file...", lambda: self._view_in_file(member.span.first))
        menu.addSeparator()
        if member.synthetic:
            rename = menu.addAction("Rename category...", self.rename_current_category)
            if is_special_category(member.category) or member.category == "as yet unclassified":
                rename.setEnabled(False)
            menu.addAction("New method in category...", self.new_method)
        else:
            menu.addAction("Move to category...", self.move_current_member)
            menu.addAction("Duplicate", self.duplicate_current_member)
            menu.addAction("Delete...", self.delete_current_member)
            if member.kind.value in {"function", "method"}:
                menu.addSeparator()
                name = callable_name_from_label(member.label)
                menu.addAction(f"Implementers of {name}...", lambda: self.show_implementers(name))
                menu.addAction(f"Senders of {name}...", lambda: self.show_senders(name))
                if member.scope != "<module>":
                    kind_menu = menu.addMenu("Convert method kind")
                    for title, kind in (("Instance method", "instance"), ("Static method", "static"), ("Class method", "class"), ("Property", "property")):
                        kind_menu.addAction(title, lambda checked=False, value=kind: self.convert_current_method(value))
        menu.exec(self.members.viewport().mapToGlobal(position))

    def _categories_context_menu(self, position):
        item = self.categories.itemAt(position)
        if item is None:
            return
        self.categories.setCurrentItem(item)
        category = item.text()
        menu = QMenu(self)
        line = min((m.span.first for m in self._visible()), default=1)
        menu.addAction("View in file...", lambda: self._view_in_file(line))
        menu.addSeparator()
        rename = menu.addAction("Rename category...", self.rename_current_category)
        # Inferred special categories do not necessarily have source metadata to rename.
        if is_special_category(category) or category == "as yet unclassified":
            rename.setEnabled(False)
            rename.setToolTip("Built-in and inferred categories cannot be renamed")
        menu.addAction("New method...", self.new_method)
        menu.addAction("New function...", self.new_function)
        menu.exec(self.categories.viewport().mapToGlobal(position))

    def _editor_context_menu(self, position):
        menu = self.editor.createStandardContextMenu()
        name = self._callable_name_at_cursor()
        if name:
            menu.addSeparator()
            action = menu.addAction(f"Implementers of {name}...")
        else:
            action = None
        chosen = menu.exec(self.editor.viewport().mapToGlobal(position))
        if action and chosen == action:
            self.show_implementers(name)

    def show_implementers(self, name):
        if not self.world or not name:
            return
        results = implementers(self.world, name)
        if len(results) == 1:
            self._navigate_code_query_result(results[0])
            return
        if not results:
            QMessageBox.information(self, f"Implementers of {name}", f"No implementations of {name} were found in this world.")
            return
        self._show_code_query_dialog(f"Implementers of {name}", results)

    def show_senders(self, name):
        if not self.world or not name:
            return
        results = senders(self.world, name)
        if not results:
            QMessageBox.information(self, f"Senders of {name}", f"No senders of {name} were found in this world.")
            return
        self._show_code_query_dialog(f"Senders of {name}", results)

    def _show_code_query_dialog(self, title, results):
        dialog = CodeQueryDialog(title, results, self.workspace, self)
        dialog.navigate_requested.connect(self._navigate_code_query_result)
        dialog.show()
        self.child_windows.append(dialog)

    def _navigate_code_query_result(self, result):
        if not self._confirm_discard():
            return
        self._select_module_path(result.module, (result.scope, result.category, result.label))
        self._select_line_result(result.line)

    def _apply_structural_edit(self, edit, description):
        if not self.doc:
            return
        if self.editor.document().isModified() and not self._confirm_discard():
            return
        try:
            validate(edit.text, str(self.doc.path))
            if changed(self.doc):
                raise StructuralEditError("The module changed on disk; reload it before structural editing")
            atomic_write(self.doc, edit.text)
            self.workspace.announce_file_changed(self.doc.path, self)
            self.index_cache.put(self.doc.path, None)
            self._open_module(self.doc.path)
            self._select_structural_result(edit.scope, edit.category, edit.preferred_name)
            self.statusBar().showMessage(description, 5000)
        except (OSError, ParseError, StructuralEditError) as exc:
            QMessageBox.critical(self, "Structural edit failed", str(exc))

    def _select_structural_result(self, scope, category, preferred_name):
        for index, item in enumerate(self.doc.scopes):
            if item.name == scope:
                self.scopes.setCurrentRow(index)
                break
        categories = self.categories.findItems(category, Qt.MatchFlag.MatchExactly)
        if categories:
            self.categories.setCurrentItem(categories[0])
        if preferred_name:
            for index, member in enumerate(self._visible()):
                if member.label.startswith(preferred_name):
                    self.members.setCurrentRow(index)
                    break

    def new_function(self):
        if not self.doc:
            return
        name, ok = QInputDialog.getText(self, "New Function", "Function name:")
        if not ok:
            return
        category, ok = QInputDialog.getText(self, "New Function", "Category:", text="Functions")
        if ok:
            try: self._apply_structural_edit(add_function(self.doc, name, category), f"Added function {name}")
            except StructuralEditError as exc: QMessageBox.warning(self, "Invalid function", str(exc))

    def new_class(self):
        if not self.doc:
            return
        name, ok = QInputDialog.getText(self, "New Class", "Class name:")
        if not ok:
            return
        category, ok = QInputDialog.getText(self, "New Class", "Category:", text="Classes")
        if ok:
            try: self._apply_structural_edit(add_class(self.doc, name, category), f"Added class {name}")
            except StructuralEditError as exc: QMessageBox.warning(self, "Invalid class", str(exc))

    def new_method(self):
        if not self.doc or not self.scope:
            return
        name, ok = QInputDialog.getText(self, "New Method", "Method name:")
        if not ok:
            return
        default = self.categories.currentItem().text() if self.categories.currentItem() else "Uncategorized"
        category, ok = QInputDialog.getText(self, "New Method", "Category:", text=default)
        if not ok:
            return
        kinds = ["instance", "static", "class", "property"] if self.scope.name != "<module>" else ["function"]
        kind, ok = QInputDialog.getItem(self, "New Method", "Kind:", kinds, 0, False)
        if ok:
            try: self._apply_structural_edit(add_method(self.doc, self.scope.name, name, category, kind), f"Added {kind} {name}")
            except StructuralEditError as exc: QMessageBox.warning(self, "Invalid method", str(exc))

    def rename_current_category(self):
        if not self.doc or not self.categories.currentItem():
            return
        old = self.categories.currentItem().text()
        new, ok = QInputDialog.getText(self, "Rename Category", "New category name:", text=old)
        if ok:
            try: self._apply_structural_edit(rename_category(self.doc, old, new, self.scope.name), f"Renamed {old} to {new}")
            except StructuralEditError as exc: QMessageBox.warning(self, "Cannot rename category", str(exc))

    def move_current_member(self):
        if not self.doc or not self.member:
            return
        category, ok = QInputDialog.getText(self, "Move Entity", "Destination category:", text=self.member.category)
        if ok:
            try: self._apply_structural_edit(move_member(self.doc, self.member, category), f"Moved entity to {category}")
            except StructuralEditError as exc: QMessageBox.warning(self, "Cannot move entity", str(exc))

    def duplicate_current_member(self):
        if self.doc and self.member:
            try: self._apply_structural_edit(duplicate_member(self.doc, self.member), "Duplicated entity")
            except StructuralEditError as exc: QMessageBox.warning(self, "Cannot duplicate entity", str(exc))

    def delete_current_member(self):
        if not self.doc or not self.member:
            return
        answer = QMessageBox.question(self, "Delete Entity", f"Delete {self.member.label}? This writes immediately to disk.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            try: self._apply_structural_edit(delete_member(self.doc, self.member), f"Deleted {self.member.label}")
            except StructuralEditError as exc: QMessageBox.warning(self, "Cannot delete entity", str(exc))

    def convert_current_method(self, kind):
        if self.doc and self.member:
            try: self._apply_structural_edit(convert_method_kind(self.doc, self.member, kind), f"Converted method to {kind}")
            except StructuralEditError as exc: QMessageBox.warning(self, "Cannot convert method", str(exc))

    def create_init_file(self):
        if not self.world or self.world.single_file:
            QMessageBox.information(self, "Create Package", "Open a directory world first.")
            return
        directory = QFileDialog.getExistingDirectory(self, "Select Package Directory", str(self.world.root))
        if not directory:
            return
        path = Path(directory).resolve()
        if self.world.root not in (path, *path.parents):
            QMessageBox.warning(self, "Invalid package directory", "Choose a directory inside the current world.")
            return
        try:
            created = create_package_init(path)
            self._refresh_world()
            self._select_module_path(created)
            self.statusBar().showMessage(f"Created {created}", 5000)
        except (OSError, StructuralEditError) as exc:
            QMessageBox.critical(self, "Cannot create __init__.py", str(exc))

    def save(self):
        if not self.doc or not self.member:
            return
        if changed(self.doc) and QMessageBox.question(self, "File changed", "The file changed outside PyBrowser. Overwrite it?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        location = (str(self.doc.path), self.member.scope, self.member.category, self.member.label)
        candidate = replacement(self.doc, self.member, self.editor.toPlainText())
        try:
            validate(candidate, str(self.doc.path))
            atomic_write(self.doc, candidate)
            self.workspace.announce_file_changed(self.doc.path, self)
            self._open_module(self.doc.path, location[1:])
            self.editor.document().setModified(False)
            self.setWindowModified(False)
            self._update_modified_indicator(False)
            self.statusBar().showMessage("Saved", 5000)
        except ParseError as exc:
            QMessageBox.critical(self, "Syntax error", f"{exc}\n\nLine: {exc.line or '?'}  Column: {exc.column or '?'}")
            if exc.line:
                self._highlight_error(exc.line, exc.column or 1)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def _highlight_error(self, line, column):
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.MoveAnchor, max(0, line - 1))
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, max(0, column - 1))
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _restore(self, scope, category, label):
        for index, item in enumerate(self.doc.scopes):
            if item.name == scope:
                self.scopes.setCurrentRow(index)
                break
        found = self.categories.findItems(category, Qt.MatchFlag.MatchExactly)
        if found:
            self.categories.setCurrentItem(found[0])
        found = self.members.findItems(label, Qt.MatchFlag.MatchExactly)
        if found:
            self.members.setCurrentItem(found[0])
        elif self.members.count():
            self.members.setCurrentRow(0)

    def closeEvent(self, event):
        if self._confirm_discard():
            self.index_cancelled.set()
            self.settings.setValue("window/geometry", self.saveGeometry())
            event.accept()
        else:
            event.ignore()
