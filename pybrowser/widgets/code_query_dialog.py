from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QSplitter, QVBoxLayout
from .editor import Editor


class CodeQueryDialog(QDialog):
    navigate_requested = Signal(object)

    def __init__(self, title, results, parent=None):
        super().__init__(parent)
        self.results_data = list(results)
        self.setWindowTitle(f"{title} [{len(self.results_data)}]")
        self.resize(900, 650)
        self.summary = QLabel(f"{len(self.results_data)} result(s)")
        self.results = QListWidget()
        self.results.addItems([item.display for item in self.results_data])
        self.preview = Editor()
        self.preview.setReadOnly(True)
        split = QSplitter()
        split.setOrientation(Qt.Orientation.Vertical)
        split.addWidget(self.results)
        split.addWidget(self.preview)
        split.setSizes([210, 440])
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(split)
        layout.addWidget(buttons)
        self.results.currentRowChanged.connect(self._preview)
        self.results.itemDoubleClicked.connect(lambda _item: self._navigate())
        if self.results.count():
            self.results.setCurrentRow(0)

    def _preview(self, row):
        self.preview.setPlainText(self.results_data[row].source if 0 <= row < len(self.results_data) else "")

    def _navigate(self):
        row = self.results.currentRow()
        if 0 <= row < len(self.results_data):
            self.navigate_requested.emit(self.results_data[row])
