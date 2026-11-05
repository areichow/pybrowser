from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QVBoxLayout


class QuickDialog(QDialog):
    def __init__(self, title, entries, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 480)
        self.entries = list(entries)
        self.filtered = list(self.entries)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Type to filter")
        self.results = QListWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self.query)
        layout.addWidget(self.results)
        self.query.textChanged.connect(self._filter)
        self.query.returnPressed.connect(self._accept_current)
        self.results.itemDoubleClicked.connect(lambda _item: self.accept())
        self._filter("")
        self.query.setFocus()

    def _filter(self, text):
        words = text.casefold().split()
        self.filtered = [entry for entry in self.entries if all(word in entry.display.casefold() for word in words)]
        self.results.clear()
        self.results.addItems([entry.display for entry in self.filtered])
        if self.results.count():
            self.results.setCurrentRow(0)

    def _accept_current(self):
        if self.results.currentRow() >= 0:
            self.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self.query.hasFocus():
            row = self.results.currentRow() + (-1 if event.key() == Qt.Key.Key_Up else 1)
            self.results.setCurrentRow(max(0, min(row, self.results.count() - 1)))
            return
        super().keyPressEvent(event)

    def selected_entry(self):
        row = self.results.currentRow()
        return self.filtered[row] if 0 <= row < len(self.filtered) else None
