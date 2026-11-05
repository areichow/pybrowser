from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QLabel, QListWidget, QMainWindow, QMessageBox, QSplitter, QVBoxLayout, QWidget
from .editor import Editor
from ..parser import ParseError, read_document, replacement, validate
from ..saving import atomic_write, changed
from ..windowing import install_window_commands


class CodeQueryDialog(QMainWindow):
    navigate_requested = Signal(object)

    def __init__(self, title, results, workspace, parent=None):
        super().__init__(None)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.workspace = workspace
        self.workspace.register(self, "query")
        self.results_data = list(results)
        self.current_document = None
        self.current_member = None
        self.setWindowTitle(f"{title} [{len(self.results_data)}][*]")
        self.resize(900, 650)
        self.summary = QLabel(f"{len(self.results_data)} result(s)")
        self.edit_status = QLabel("No pending edits")
        self.edit_status.setStyleSheet("color: #8a8d91; font-weight: bold")
        self.results = QListWidget(); self.results.addItems([item.display for item in self.results_data])
        self.preview = Editor()
        self.preview.browse_class_requested.connect(self.workspace.request_class_browser)
        self.preview.modificationChanged.connect(self._modified_changed)
        split = QSplitter(Qt.Orientation.Vertical); split.addWidget(self.results); split.addWidget(self.preview); split.setSizes([210, 440])
        central = QWidget()
        layout = QVBoxLayout(central); layout.addWidget(self.summary); layout.addWidget(self.edit_status); layout.addWidget(split)
        self.setCentralWidget(central)
        self.results.currentRowChanged.connect(self._preview)
        self.results.itemDoubleClicked.connect(lambda _item: self._navigate())
        self.workspace.file_changed.connect(self._workspace_changed)
        save = QAction("Save", self); save.setShortcut(QKeySequence.StandardKey.Save); save.triggered.connect(self.save)
        abandon = QAction("Abandon", self); abandon.setShortcut("Ctrl+L"); abandon.triggered.connect(self.abandon)
        self.addActions([save, abandon])
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([save, abandon])
        install_window_commands(self, self.workspace, file_menu)
        if self.results.count(): self.results.setCurrentRow(0)

    def _modified_changed(self, modified):
        self.setWindowModified(modified)
        if modified:
            self.edit_status.setText("● Unsaved changes: Ctrl+S to save, Ctrl+L to abandon")
            self.edit_status.setStyleSheet("color: #ffd166; font-weight: bold")
            item = self.results.currentItem()
            if item:
                item.setForeground(Qt.GlobalColor.yellow)
                font = item.font(); font.setBold(True); item.setFont(font)
        else:
            self.edit_status.setText("No pending edits")
            self.edit_status.setStyleSheet("color: #8a8d91; font-weight: bold")
            item = self.results.currentItem()
            if item:
                item.setForeground(self.palette().text().color())
                font = item.font(); font.setBold(False); item.setFont(font)

    def _preview(self, row):
        if self.preview.document().isModified():
            answer = QMessageBox.question(self, "Abandon changes?", "Do you want to abandon changes to this Member?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.No: return
        if not (0 <= row < len(self.results_data)): return
        result = self.results_data[row]
        try:
            self.current_document = read_document(result.module)
            scope = next((s for s in self.current_document.scopes if s.name == result.scope), None)
            self.current_member = next((m for m in scope.members if not m.synthetic and m.label == result.label), None) if scope else None
            source = self.current_document.source(self.current_member) if self.current_member else result.source
            self.preview.setPlainText(source); self.preview.document().setModified(False)
        except OSError as exc: QMessageBox.warning(self, "Cannot load source", str(exc))

    def save(self):
        if not self.current_document or not self.current_member: return
        if changed(self.current_document):
            QMessageBox.warning(self, "File changed", "The file changed in another window. Select the result again before saving."); return
        candidate = replacement(self.current_document, self.current_member, self.preview.toPlainText())
        try:
            validate(candidate, str(self.current_document.path)); atomic_write(self.current_document, candidate)
            self.current_document = read_document(self.current_document.path)
            self.preview.document().setModified(False)
            self.workspace.announce_file_changed(self.current_document.path, self)
        except (OSError, ParseError) as exc: QMessageBox.critical(self, "Save failed", str(exc))

    def abandon(self):
        if not self.current_document or not self.current_member:
            return
        self.preview.setPlainText(self.current_document.source(self.current_member))
        self.preview.document().setModified(False)

    def _navigate(self):
        row = self.results.currentRow()
        if 0 <= row < len(self.results_data): self.navigate_requested.emit(self.results_data[row])

    def _workspace_changed(self, path, origin):
        if origin is self or not self.current_document or Path(path) != self.current_document.path: return
        if not self.preview.document().isModified(): self._preview(self.results.currentRow())

    def closeEvent(self, event):
        if not self.preview.document().isModified(): event.accept(); return
        answer = QMessageBox.question(self, "Abandon changes?", "Do you want to abandon changes in this query window?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        event.accept() if answer == QMessageBox.StandardButton.Yes else event.ignore()
