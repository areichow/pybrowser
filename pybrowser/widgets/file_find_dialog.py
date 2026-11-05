from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)


class FileFindDialog(QDialog):
    find_next = Signal(str, bool, bool, bool)
    find_all = Signal(str, bool, bool)
    replace_one = Signal(str, str, bool, bool, bool)
    replace_all = Signal(str, str, bool, bool)

    def __init__(self, parent=None, initial="", replace_tab=False):
        super().__init__(parent)
        self.setWindowTitle("Find and Replace")
        self.setModal(False)
        self.resize(610, 260)
        self.tabs = QTabWidget()
        self.find_page = QWidget(); self.replace_page = QWidget()
        self.find_text = QLineEdit(initial)
        self.replace_find_text = QLineEdit(initial)
        self.replace_text = QLineEdit()
        self.match_case = QCheckBox("Match case")
        self.whole_word = QCheckBox("Match whole word only")
        self.wrap = QCheckBox("Wrap around"); self.wrap.setChecked(True)
        self.backward = QCheckBox("Backward direction")
        self.replace_match_case = QCheckBox("Match case")
        self.replace_whole_word = QCheckBox("Match whole word only")
        self.replace_wrap = QCheckBox("Wrap around"); self.replace_wrap.setChecked(True)
        self.status = QLabel("")
        self._build_find_page(); self._build_replace_page()
        self.tabs.addTab(self.find_page, "Find")
        self.tabs.addTab(self.replace_page, "Replace")
        self.tabs.setCurrentIndex(1 if replace_tab else 0)
        close = QPushButton("Close"); close.clicked.connect(self.close)
        layout = QVBoxLayout(self); layout.addWidget(self.tabs); layout.addWidget(self.status)
        row = QHBoxLayout(); row.addStretch(1); row.addWidget(close); layout.addLayout(row)
        self.find_text.returnPressed.connect(self._emit_find_next)
        self.replace_find_text.returnPressed.connect(self._emit_replace_one)

    def _build_find_page(self):
        form = QFormLayout(); form.addRow("Find what:", self.find_text)
        find_next = QPushButton("Find Next"); find_next.clicked.connect(self._emit_find_next)
        find_all = QPushButton("Find All in Current File"); find_all.clicked.connect(self._emit_find_all)
        buttons = QHBoxLayout(); buttons.addWidget(find_next); buttons.addWidget(find_all); buttons.addStretch(1)
        layout = QVBoxLayout(self.find_page); layout.addLayout(form); layout.addWidget(self.backward); layout.addWidget(self.whole_word); layout.addWidget(self.match_case); layout.addWidget(self.wrap); layout.addLayout(buttons)

    def _build_replace_page(self):
        form = QFormLayout(); form.addRow("Find what:", self.replace_find_text); form.addRow("Replace with:", self.replace_text)
        replace = QPushButton("Replace"); replace.clicked.connect(self._emit_replace_one)
        replace_all = QPushButton("Replace All"); replace_all.clicked.connect(self._emit_replace_all)
        buttons = QHBoxLayout(); buttons.addWidget(replace); buttons.addWidget(replace_all); buttons.addStretch(1)
        layout = QVBoxLayout(self.replace_page); layout.addLayout(form); layout.addWidget(self.replace_whole_word); layout.addWidget(self.replace_match_case); layout.addWidget(self.replace_wrap); layout.addLayout(buttons)

    def _emit_find_next(self):
        self.find_next.emit(self.find_text.text(), self.match_case.isChecked(), self.whole_word.isChecked(), self.backward.isChecked())

    def _emit_find_all(self):
        self.find_all.emit(self.find_text.text(), self.match_case.isChecked(), self.whole_word.isChecked())

    def _emit_replace_one(self):
        self.replace_one.emit(self.replace_find_text.text(), self.replace_text.text(), self.replace_match_case.isChecked(), self.replace_whole_word.isChecked(), False)

    def _emit_replace_all(self):
        self.replace_all.emit(self.replace_find_text.text(), self.replace_text.text(), self.replace_match_case.isChecked(), self.replace_whole_word.isChecked())

    def focus_find(self):
        self.tabs.setCurrentIndex(0); self.find_text.setFocus(); self.find_text.selectAll()

    def focus_replace(self):
        self.tabs.setCurrentIndex(1); self.replace_find_text.setFocus(); self.replace_find_text.selectAll()
