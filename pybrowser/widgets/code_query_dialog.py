from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QLabel, QListWidget, QMainWindow, QMessageBox, QSplitter, QVBoxLayout, QWidget
from .editor import Editor
from ..parser import ParseError, read_document, replacement
from ..source_write_service import SaveRequest, SourceConflictError, SourcePostCommitError
from ..windowing import install_window_commands
from ..member_projection import MemberProjection, project_member, restore_member


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
        self.member_projection = MemberProjection("", "", False, "No Member selected")
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
            self.current_document = self.workspace.read_document(result.module)
            scope = next((s for s in self.current_document.scopes if s.name == result.scope), None)
            self.current_member = next((m for m in scope.members if not m.synthetic and m.label == result.label), None) if scope else None
            if self.current_member:
                self.member_projection = project_member(self.current_document, self.current_member, True)
                source = self.member_projection.text
            else:
                self.member_projection = MemberProjection(result.source, "", False, "No editable Member")
                source = result.source
            self.preview.setPlainText(source); self.preview.document().setModified(False)
        except OSError as exc: QMessageBox.warning(self, "Cannot load source", str(exc))

    def save(self):
        if not self.current_document or not self.current_member: return
        restored_source = restore_member(self.member_projection, self.preview.toPlainText())
        candidate = replacement(self.current_document, self.current_member, restored_source)
        try:
            result = self.workspace.write_service.save_document(SaveRequest(
                self.current_document, candidate, "save_member",
                f"Save query Member {self.current_member.label}", origin=self,
            ))
            self.current_document = result.document
            self.preview.document().setModified(False)
            if result.warnings:
                QMessageBox.warning(self, "Committed with warning", "\n".join(result.warnings))
        except SourceConflictError as exc: QMessageBox.warning(self, "File changed", str(exc))
        except SourcePostCommitError as exc: QMessageBox.warning(self, "Committed with warning", str(exc))
        except (OSError, ParseError) as exc: QMessageBox.critical(self, "Save failed", str(exc))

    def abandon(self):
        if not self.current_document or not self.current_member:
            return
        self.member_projection = project_member(self.current_document, self.current_member, True)
        self.preview.setPlainText(self.member_projection.text)
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
