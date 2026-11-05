from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QWidget, QHBoxLayout


class BusyIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.label = QLabel("Source model ready")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setTextVisible(True)
        self.progress.hide()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.addWidget(self.label)
        layout.addStretch(1)
        layout.addWidget(self.progress)

    def begin(self, text, total=0):
        self.label.setText(text)
        self.progress.show()
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(0)
        else:
            self.progress.setRange(0, 0)

    def update_progress(self, completed, total, detail=""):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(completed)
        suffix = f"  {detail}" if detail else ""
        self.label.setText(f"Source model working: {completed}/{total}{suffix}")

    def end(self, text="Source model ready"):
        self.label.setText(text)
        self.progress.hide()
