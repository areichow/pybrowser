from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout,
)


class ReplaceDialog(QDialog):
    replace_one = Signal(str, str, bool)
    replace_all = Signal(str, str, bool)

    def __init__(self, parent=None, initial=""):
        super().__init__(parent)
        self.setWindowTitle("Replace in Current Entity")
        self.find_text = QLineEdit(initial)
        self.replace_text = QLineEdit()
        self.case_sensitive = QCheckBox("Case sensitive")
        self.status = QLabel("")
        form = QFormLayout()
        form.addRow("Find:", self.find_text)
        form.addRow("Replace with:", self.replace_text)
        row = QHBoxLayout()
        replace = QPushButton("Replace")
        replace_all = QPushButton("Replace All")
        close = QPushButton("Close")
        row.addWidget(replace)
        row.addWidget(replace_all)
        row.addStretch(1)
        row.addWidget(close)
        replace.clicked.connect(lambda: self.replace_one.emit(self.find_text.text(), self.replace_text.text(), self.case_sensitive.isChecked()))
        replace_all.clicked.connect(lambda: self.replace_all.emit(self.find_text.text(), self.replace_text.text(), self.case_sensitive.isChecked()))
        close.clicked.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.case_sensitive)
        layout.addWidget(self.status)
        layout.addLayout(row)
