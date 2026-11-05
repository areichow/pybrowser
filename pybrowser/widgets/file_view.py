from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QTextCursor
from PySide6.QtWidgets import QMainWindow, QMessageBox
from .editor import Editor
from ..parser import ParseError, read_document, validate
from ..saving import atomic_write, changed


class FileViewWindow(QMainWindow):
    def __init__(self, path: Path, workspace, line=1, parent=None):
        super().__init__(parent)
        self.path = Path(path).resolve()
        self.workspace = workspace
        self.document_model = read_document(self.path)
        self.editor = Editor()
        self.setCentralWidget(self.editor)
        self.editor.browse_class_requested.connect(self.workspace.request_class_browser)
        self.setWindowTitle(f"{self.path.name} - File View[*]")
        self.resize(1000, 800)
        self.editor.setPlainText(self.document_model.text)
        self.editor.document().setModified(False)
        self.editor.modificationChanged.connect(self.setWindowModified)
        self.workspace.file_changed.connect(self._workspace_changed)
        save = QAction("Save", self); save.setShortcut(QKeySequence.StandardKey.Save); save.triggered.connect(self.save)
        abandon = QAction("Abandon Changes", self); abandon.setShortcut("Ctrl+L"); abandon.triggered.connect(self.abandon)
        self.addActions([save, abandon])
        self.menuBar().addMenu("&File").addActions([save, abandon])
        self.goto_line(line)

    def goto_line(self, line):
        cursor = self.editor.textCursor(); cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.MoveAnchor, max(0, line - 1))
        self.editor.setTextCursor(cursor); self.editor.centerCursor()

    def save(self):
        if changed(self.document_model):
            QMessageBox.warning(self, "File changed", "The file changed in another window. Reload it before saving.")
            return
        text = self.editor.toPlainText()
        try:
            validate(text, str(self.path)); atomic_write(self.document_model, text)
            self.document_model = read_document(self.path)
            self.editor.document().setModified(False)
            self.workspace.announce_file_changed(self.path, self)
        except (OSError, ParseError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def abandon(self):
        self.document_model = read_document(self.path)
        self.editor.setPlainText(self.document_model.text)
        self.editor.document().setModified(False)

    def _workspace_changed(self, path, origin):
        if Path(path) != self.path or origin is self: return
        if self.editor.document().isModified():
            self.setWindowTitle(f"{self.path.name} - File View [external change; unsaved edits] [*]")
            return
        position = self.editor.textCursor().position(); self.abandon()
        cursor = self.editor.textCursor(); cursor.setPosition(min(position, len(self.editor.toPlainText()))); self.editor.setTextCursor(cursor)

    def closeEvent(self, event):
        if not self.editor.document().isModified(): event.accept(); return
        answer = QMessageBox.question(self, "Abandon changes?", "Do you want to abandon changes in this file view?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        event.accept() if answer == QMessageBox.StandardButton.Yes else event.ignore()
