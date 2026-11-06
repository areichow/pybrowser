from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QInputDialog, QLabel, QListWidget, QMainWindow, QMessageBox, QSplitter,
    QVBoxLayout, QWidget,
)

from .editor import Editor
from .file_find_dialog import FileFindDialog
from ..file_search import compile_pattern, find_hits
from ..parser import ParseError, read_document
from ..saving import changed
from ..source_write_service import SaveRequest, SourceConflictError, SourcePostCommitError
from ..windowing import install_window_commands


class FileViewWindow(QMainWindow):
    def __init__(self, path: Path, workspace, line=1, parent=None):
        super().__init__(None)
        self.path = Path(path).resolve()
        self.workspace = workspace
        self.workspace.register(self, "file-view")
        self.document_model = read_document(self.path)
        self.editor = Editor()
        self.find_dialog = None
        self.last_find = ("", False, False)
        self.hits = ()

        self.results = QListWidget()
        self.results.setMinimumHeight(120)
        self.results.hide()
        self.results.itemActivated.connect(self._activate_hit)
        self.results.itemClicked.connect(self._activate_hit)
        self.result_summary = QLabel("")
        self.result_summary.hide()
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(2, 2, 2, 2)
        bottom_layout.addWidget(self.result_summary)
        bottom_layout.addWidget(self.results)
        bottom.hide()
        self.results_container = bottom
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.editor)
        split.addWidget(bottom)
        split.setSizes([760, 160])
        self.setCentralWidget(split)

        self.editor.browse_class_requested.connect(self.workspace.request_class_browser)
        self.setWindowTitle(f"{self.path.name} - File View[*]")
        self.resize(1000, 800)
        self.editor.setPlainText(self.document_model.text)
        self.editor.document().setModified(False)
        self.editor.modificationChanged.connect(self.setWindowModified)
        self.workspace.file_changed.connect(self._workspace_changed)

        save = QAction("Save", self); save.setShortcut(QKeySequence.StandardKey.Save); save.triggered.connect(self.save)
        abandon = QAction("Abandon Changes", self); abandon.setShortcut("Ctrl+L"); abandon.triggered.connect(self.abandon)
        find = QAction("Find...", self); find.setShortcut("Ctrl+F"); find.triggered.connect(self.show_find)
        find_next = QAction("Find Next", self); find_next.setShortcut("Ctrl+G"); find_next.triggered.connect(self.find_next)
        replace = QAction("Replace...", self); replace.setShortcut("Ctrl+H"); replace.triggered.connect(self.show_replace)
        goto = QAction("Go to Line...", self); goto.setShortcut("Ctrl+Shift+G"); goto.triggered.connect(self.prompt_goto_line)
        self.addActions([save, abandon, find, find_next, replace, goto])
        file_menu = self.menuBar().addMenu("&File"); file_menu.addActions([save, abandon])
        edit_menu = self.menuBar().addMenu("&Edit"); edit_menu.addActions([find, find_next, replace, goto])
        install_window_commands(self, self.workspace, file_menu)
        self.goto_line(line)

    def _selected_text(self):
        return self.editor.textCursor().selectedText().replace("\u2029", "\n")

    def _ensure_find_dialog(self, replace=False):
        initial = self._selected_text()
        if self.find_dialog is None:
            self.find_dialog = FileFindDialog(self, initial, replace)
            self.find_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            self.find_dialog.find_next.connect(self._find_next)
            self.find_dialog.find_all.connect(self.find_all)
            self.find_dialog.replace_one.connect(self.replace_one)
            self.find_dialog.replace_all.connect(self.replace_all)
        elif initial:
            self.find_dialog.find_text.setText(initial)
            self.find_dialog.replace_find_text.setText(initial)
        self.find_dialog.show(); self.find_dialog.raise_(); self.find_dialog.activateWindow()
        return self.find_dialog

    def show_find(self): self._ensure_find_dialog(False).focus_find()
    def show_replace(self): self._ensure_find_dialog(True).focus_replace()

    def _find_next(self, query, match_case=False, whole_word=False, backward=False):
        self.last_find = (query, match_case, whole_word)
        hits = find_hits(self.editor.toPlainText(), query, match_case, whole_word)
        if not hits:
            if self.find_dialog: self.find_dialog.status.setText("No matches")
            return
        position = self.editor.textCursor().selectionStart() if backward else self.editor.textCursor().selectionEnd()
        candidates = [hit for hit in hits if hit.end <= position] if backward else [hit for hit in hits if hit.start >= position]
        hit = (candidates[-1] if candidates and backward else candidates[0] if candidates else hits[-1] if backward else hits[0])
        self._select_hit(hit)
        if self.find_dialog: self.find_dialog.status.setText(f"Line {hit.line}, column {hit.column} of {len(hits)} match(es)")

    def find_next(self):
        query, match_case, whole_word = self.last_find
        if not query:
            self.show_find(); return
        self._find_next(query, match_case, whole_word, False)

    def find_all(self, query, match_case=False, whole_word=False):
        self.last_find = (query, match_case, whole_word)
        self.hits = find_hits(self.editor.toPlainText(), query, match_case, whole_word)
        self.results.clear(); self.results.addItems([hit.display for hit in self.hits])
        self.result_summary.setText(f"{len(self.hits)} match(es) in {self.path.name}")
        self.results_container.show(); self.results.show(); self.result_summary.show()
        if self.hits: self.results.setCurrentRow(0)
        if self.find_dialog: self.find_dialog.status.setText(f"{len(self.hits)} match(es)")

    def _activate_hit(self, item):
        row = self.results.row(item)
        if 0 <= row < len(self.hits): self._select_hit(self.hits[row])

    def _select_hit(self, hit):
        cursor = self.editor.textCursor(); cursor.setPosition(hit.start); cursor.setPosition(hit.end, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor); self.editor.centerCursor(); self.editor.setFocus()

    def replace_one(self, query, replacement, match_case=False, whole_word=False, _backward=False):
        selected = self._selected_text()
        pattern = compile_pattern(query, match_case, whole_word)
        if pattern and selected and pattern.fullmatch(selected):
            self.editor.textCursor().insertText(replacement)
        self._find_next(query, match_case, whole_word, False)

    def replace_all(self, query, replacement, match_case=False, whole_word=False):
        pattern = compile_pattern(query, match_case, whole_word)
        if pattern is None: return
        text, count = pattern.subn(lambda _match: replacement, self.editor.toPlainText())
        if count:
            cursor = self.editor.textCursor(); cursor.beginEditBlock(); cursor.select(QTextCursor.SelectionType.Document); cursor.insertText(text); cursor.endEditBlock()
        if self.find_dialog: self.find_dialog.status.setText(f"Replaced {count} occurrence(s)")
        self.results_container.hide()

    def prompt_goto_line(self):
        line, ok = QInputDialog.getInt(self, "Go to Line", "Line number:", self.editor.textCursor().blockNumber() + 1, 1, max(1, self.editor.blockCount()))
        if ok: self.goto_line(line)

    def goto_line(self, line):
        cursor = self.editor.textCursor(); cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.MoveAnchor, max(0, line - 1))
        self.editor.setTextCursor(cursor); self.editor.centerCursor(); self.editor.setFocus()

    def save(self):
        text = self.editor.toPlainText()
        try:
            result = self.workspace.write_service.save_document(SaveRequest(
                self.document_model, text, "save_file", f"Save File View {self.path.name}", origin=self,
            ))
            self.document_model = result.document; self.editor.document().setModified(False)
        except SourceConflictError as exc: QMessageBox.warning(self, "File changed", str(exc))
        except SourcePostCommitError as exc: QMessageBox.warning(self, "Committed with warning", str(exc))
        except (OSError, ParseError) as exc: QMessageBox.critical(self, "Save failed", str(exc))

    def abandon(self):
        self.document_model = read_document(self.path); self.editor.setPlainText(self.document_model.text); self.editor.document().setModified(False)
        self.results_container.hide()

    def _workspace_changed(self, path, origin):
        if Path(path) != self.path or origin is self: return
        if self.editor.document().isModified():
            self.setWindowTitle(f"{self.path.name} - File View [external change; unsaved edits] [*]"); return
        position = self.editor.textCursor().position(); self.abandon()
        cursor = self.editor.textCursor(); cursor.setPosition(min(position, len(self.editor.toPlainText()))); self.editor.setTextCursor(cursor)

    def closeEvent(self, event):
        if not self.editor.document().isModified(): event.accept(); return
        answer = QMessageBox.question(self, "Abandon changes?", "Do you want to abandon changes in this file view?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        event.accept() if answer == QMessageBox.StandardButton.Yes else event.ignore()
