from __future__ import annotations

import difflib
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ..windowing import install_window_commands


class StructuralHistoryWindow(QMainWindow):
    def __init__(self, workspace, parent=None):
        super().__init__(None)
        self.workspace = workspace
        self.workspace.register(self, "history")
        self.journal = workspace.journal
        self.transactions = []
        self.setWindowTitle("Structural History")
        self.resize(1050, 720)
        self.list = QListWidget()
        self.detail = QLabel("Select a transaction")
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.diff = QPlainTextEdit(); self.diff.setReadOnly(True)
        right = QWidget(); right_layout = QVBoxLayout(right); right_layout.addWidget(self.detail); right_layout.addWidget(self.diff, 1)
        split = QSplitter(Qt.Orientation.Horizontal); split.addWidget(self.list); split.addWidget(right); split.setSizes([360, 690])
        before = QPushButton("Restore Before As..."); before.clicked.connect(lambda: self.restore_as("before"))
        after = QPushButton("Restore After As..."); after.clicked.connect(lambda: self.restore_as("after"))
        self.pin = QPushButton("Pin"); self.pin.clicked.connect(self.toggle_pin)
        refresh = QPushButton("Refresh"); refresh.clicked.connect(self.refresh)
        buttons = QHBoxLayout(); buttons.addWidget(before); buttons.addWidget(after); buttons.addWidget(self.pin); buttons.addStretch(1); buttons.addWidget(refresh)
        central = QWidget(); layout = QVBoxLayout(central); layout.addWidget(split, 1); layout.addLayout(buttons); self.setCentralWidget(central)
        file_menu = self.menuBar().addMenu("&File")
        install_window_commands(self, workspace, file_menu)
        self.list.currentRowChanged.connect(self._selected)
        self.refresh()

    def refresh(self):
        self.transactions = list(self.journal.transactions()) if self.journal else []
        self.list.clear()
        for tx in self.transactions:
            pin = "📌 " if tx.pinned else ""
            self.list.addItem(f"{pin}{tx.timestamp[:19]}  [{tx.status}]  {tx.description}")
        if self.transactions: self.list.setCurrentRow(0)
        else: self.detail.setText("No recovery transactions for this World"); self.diff.clear()

    def current_transaction(self):
        row = self.list.currentRow()
        return self.transactions[row] if 0 <= row < len(self.transactions) else None

    def _selected(self, row):
        tx = self.current_transaction()
        if tx is None: return
        files = tx.manifest.get("files", [])
        states = self.journal.inspect_state(tx)
        lines = [tx.description, f"Operation: {tx.manifest.get('operation')}", f"Status: {tx.status}", f"Transaction: {tx.transaction_id}", ""]
        for (path, state), item in zip(states, files):
            lines.extend([str(path), f"Disk state: {state}", f"Before: {item.get('before_sha256')}", f"After:  {item.get('after_sha256')}", ""])
        self.detail.setText("\n".join(lines))
        self.pin.setText("Unpin" if tx.pinned else "Pin")
        if files:
            before = self.journal.snapshot_path(tx, "before").read_text(encoding=files[0].get("encoding", "utf-8"), errors="replace").splitlines()
            after = self.journal.snapshot_path(tx, "after").read_text(encoding=files[0].get("encoding", "utf-8"), errors="replace").splitlines()
            diff = difflib.unified_diff(before, after, fromfile="before/" + files[0]["relative_path"], tofile="after/" + files[0]["relative_path"], lineterm="")
            self.diff.setPlainText("\n".join(diff) or "No textual differences")

    def restore_as(self, side):
        tx = self.current_transaction()
        if tx is None or not tx.manifest.get("files"): return
        original = Path(tx.manifest["files"][0]["path"])
        destination, _ = QFileDialog.getSaveFileName(self, f"Restore {side.title()} Snapshot As", str(original.with_name(original.stem + f".{side}" + original.suffix)), "Python files (*.py);;All files (*)")
        if not destination: return
        try:
            self.journal.restore_as(tx, side, Path(destination))
            self.statusBar().showMessage(f"Restored {side} snapshot to {destination}", 6000)
        except OSError as exc: QMessageBox.critical(self, "Restore failed", str(exc))

    def toggle_pin(self):
        tx = self.current_transaction()
        if tx is None: return
        self.journal.set_pinned(tx, not tx.pinned)
        self.refresh()
