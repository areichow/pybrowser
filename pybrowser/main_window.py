from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QPlainTextEdit, QSplitter, QStatusBar,
    QVBoxLayout, QWidget,
)
from .parser import ParseError, read_document, replacement, validate
from .saving import atomic_write, changed
from .search import SearchMatch, find_all
from .widgets.editor import Editor

class MainWindow(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.doc = None
        self.scope = None
        self.member = None
        self.loading = False
        self.search_matches: tuple[SearchMatch, ...] = ()
        self.search_index = -1
        self.search_source = ""
        self.resize(1400, 900)
        self.setWindowTitle("PyBrowser")
        self._ui()
        self._actions()
        if path:
            self.open(path)

    def _ui(self):
        self.modules = QListWidget()
        self.scopes = QListWidget()
        self.categories = QListWidget()
        self.members = QListWidget()
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
        self.modules.currentRowChanged.connect(self._module)
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
        font = QFont("0xProto Nerd Font", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(font)
        self.editor.textChanged.connect(self._modified)

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(4, 0, 4, 4)
        lower_layout.addWidget(find_bar)
        lower_layout.addWidget(self.crumb)
        lower_layout.addWidget(self.editor)
        main = QSplitter(Qt.Orientation.Vertical)
        main.addWidget(top)
        main.addWidget(lower)
        main.setSizes([280, 620])
        self.setCentralWidget(main)
        self.setStatusBar(QStatusBar())

    def _actions(self):
        open_action = QAction("Open Python File...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.choose)
        save_action = QAction("Save Member", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save)
        find_action = QAction("Find", self)
        find_action.setShortcut(QKeySequence.StandardKey.Find)
        find_action.triggered.connect(self.focus_find)
        next_action = QAction("Find Next", self)
        next_action.setShortcut("Ctrl+G")
        next_action.triggered.connect(self.find_next)
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([open_action, save_action])
        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addActions([find_action, next_action])
        self.addActions([open_action, save_action, find_action, next_action])

    def focus_find(self):
        self.find_text.setFocus()
        self.find_text.selectAll()

    def _search_text_changed(self):
        self._clear_search_highlights()
        self.search_matches = ()
        self.search_index = -1
        self.search_source = ""
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
        selection = QPlainTextEdit.ExtraSelection()
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
        if not self.loading:
            self.setWindowModified(self.editor.document().isModified())
            if self.search_source:
                self._search_text_changed()

    def _confirm_discard(self):
        if not self.editor.document().isModified():
            return True
        answer = QMessageBox.question(self, "Unsaved member edit", "Save the current member before navigating?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            self.save()
            return not self.editor.document().isModified()
        return answer == QMessageBox.StandardButton.Discard

    def choose(self):
        name, _ = QFileDialog.getOpenFileName(self, "Open Python File", "", "Python files (*.py)")
        if name and self._confirm_discard():
            self.open(Path(name))

    def open(self, path, restore=None):
        try:
            self.doc = read_document(path)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot open file", str(exc))
            return
        self.loading = True
        self.modules.clear()
        self.modules.addItem(self.doc.path.name)
        self.modules.setCurrentRow(0)
        self.loading = False
        self.setWindowTitle(self.doc.path.name + "[*] - PyBrowser")
        self._search_text_changed()
        if restore:
            self._restore(*restore)

    def _module(self, row):
        if row < 0 or not self.doc:
            return
        self.scopes.blockSignals(True)
        self.scopes.clear()
        self.scopes.addItems([item.name for item in self.doc.scopes])
        self.scopes.blockSignals(False)
        self.scopes.setCurrentRow(0)

    def _scope(self, row):
        if row < 0 or not self.doc:
            return
        if self.member and not self.loading and not self._confirm_discard():
            return
        self.scope = self.doc.scopes[row]
        self.categories.clear()
        self.categories.addItems(sorted(dict.fromkeys(item.category for item in self.scope.members), key=lambda value: (value == "Uncategorized", value.casefold())))
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
            self.crumb.setText(f"{self.doc.path.name} > {member.scope} > {member.category} > {member.label}")
        else:
            self.editor.clear()
        self.loading = False
        self.setWindowModified(False)
        if self.search_source == "entity":
            self._search_text_changed()

    def save(self):
        if not self.doc or not self.member:
            return
        if changed(self.doc) and QMessageBox.question(self, "File changed", "The file changed outside PyBrowser. Overwrite it?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        location = (self.member.scope, self.member.category, self.member.label)
        candidate = replacement(self.doc, self.member, self.editor.toPlainText())
        try:
            validate(candidate, str(self.doc.path))
            atomic_write(self.doc, candidate)
            self.open(self.doc.path, location)
            self.editor.document().setModified(False)
            self.setWindowModified(False)
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
        event.accept() if self._confirm_discard() else event.ignore()
