from __future__ import annotations

import difflib
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ..windowing import install_window_commands
from ..workspace import WorkspaceUndoError


class StructuralHistoryWindow(QMainWindow):
    def __init__(self, workspace, parent=None):
        super().__init__(None)
        self.workspace = workspace
        self.workspace.register(self, "history")
        self.journal = workspace.journal
        self.transactions = []
        self.setWindowTitle("Structural History")
        self.resize(1100, 740)
        self.list = QListWidget()
        self.detail = QLabel("Select a transaction")
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.diff = QPlainTextEdit(); self.diff.setReadOnly(True)
        right = QWidget(); right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.detail); right_layout.addWidget(self.diff, 1)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.list); split.addWidget(right); split.setSizes([380, 720])
        self.undo_button = QPushButton("Undo Selected"); self.undo_button.clicked.connect(lambda: self.apply_selected("undo"))
        self.redo_button = QPushButton("Redo Selected"); self.redo_button.clicked.connect(lambda: self.apply_selected("redo"))
        before = QPushButton("Restore Before As..."); before.clicked.connect(lambda: self.restore_as("before"))
        after = QPushButton("Restore After As..."); after.clicked.connect(lambda: self.restore_as("after"))
        open_file = QPushButton("Open File View"); open_file.clicked.connect(self.open_file_view)
        self.pin = QPushButton("Pin"); self.pin.clicked.connect(self.toggle_pin)
        refresh = QPushButton("Refresh"); refresh.clicked.connect(self.refresh)
        buttons = QHBoxLayout()
        for button in (self.undo_button, self.redo_button, before, after, open_file, self.pin):
            buttons.addWidget(button)
        buttons.addStretch(1); buttons.addWidget(refresh)
        central = QWidget(); layout = QVBoxLayout(central)
        layout.addWidget(split, 1); layout.addLayout(buttons); self.setCentralWidget(central)
        file_menu = self.menuBar().addMenu("&File")
        install_window_commands(self, workspace, file_menu)
        self.list.currentRowChanged.connect(self._selected)
        self.workspace.history_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        selected_id = self.current_transaction().transaction_id if self.current_transaction() else None
        self.transactions = list(self.journal.transactions()) if self.journal else []
        self.list.clear()
        selected_row = 0
        for row, tx in enumerate(self.transactions):
            pin = "PIN " if tx.pinned else ""
            damaged = " / damaged" if tx.damaged else ""
            self.list.addItem(f"{pin}{tx.timestamp[:19]}  [{tx.status}{damaged}]  {tx.description}")
            if tx.transaction_id == selected_id:
                selected_row = row
        if self.transactions:
            self.list.setCurrentRow(selected_row)
        else:
            self.detail.setText("No recovery transactions for this World"); self.diff.clear()

    def current_transaction(self):
        row = self.list.currentRow()
        return self.transactions[row] if 0 <= row < len(self.transactions) else None

    def _selected(self, row):
        tx = self.current_transaction()
        if tx is None:
            return
        files = tx.manifest.get("files", [])
        states = self.journal.inspect_state(tx)
        lines = [tx.description, f"Operation: {tx.manifest.get('operation')}",
                 f"Status: {tx.status}", f"Transaction: {tx.transaction_id}", ""]
        for (path, state), item in zip(states, files):
            lines.extend([str(path), f"Disk state: {state}",
                          f"Before: {item.get('before_sha256')}",
                          f"After:  {item.get('after_sha256')}", ""])
        self.detail.setText("\n".join(lines))
        self.pin.setText("Unpin" if tx.pinned else "Pin")
        self.undo_button.setEnabled(tx.status in {"committed", "redone"} and not tx.damaged)
        self.redo_button.setEnabled(tx.status == "undone" and not tx.damaged)
        if files:
            try:
                before = self.journal.snapshot_path(tx, "before").read_text(
                    encoding=files[0].get("encoding", "utf-8"), errors="replace").splitlines()
                after = self.journal.snapshot_path(tx, "after").read_text(
                    encoding=files[0].get("encoding", "utf-8"), errors="replace").splitlines()
                diff = difflib.unified_diff(before, after,
                    fromfile="before/" + files[0]["relative_path"],
                    tofile="after/" + files[0]["relative_path"], lineterm="")
                self.diff.setPlainText("\n".join(diff) or "No textual differences")
            except OSError as exc:
                self.diff.setPlainText(f"Snapshot unavailable: {exc}")

    def apply_selected(self, direction):
        tx = self.current_transaction()
        if tx is None:
            return
        try:
            result, _paths = self.workspace.perform_history_action(direction, tx)
            verb = "Undid" if direction == "undo" else "Redid"
            self.statusBar().showMessage(f"{verb}: {result.description}", 6000)
        except WorkspaceUndoError as exc:
            if exc.windows:
                QMessageBox.warning(self, f"Cannot {direction.title()}", str(exc))
                self.workspace.activate_window(exc.windows[0])
            else:
                QMessageBox.warning(self, f"Structural {direction.title()} Conflict", str(exc))
        self.refresh()

    def restore_as(self, side):
        tx = self.current_transaction()
        if tx is None or not tx.manifest.get("files"):
            return
        original = Path(tx.manifest["files"][0]["path"])
        suggested = original.with_name(original.stem + f".{side}" + original.suffix)
        destination, _ = QFileDialog.getSaveFileName(
            self, f"Restore {side.title()} Snapshot As", str(suggested),
            "Python files (*.py);;All files (*)")
        if not destination:
            return
        try:
            self.journal.restore_as(tx, side, Path(destination))
            self.statusBar().showMessage(f"Restored {side} snapshot to {destination}", 6000)
        except OSError as exc:
            QMessageBox.critical(self, "Restore failed", str(exc))

    def open_file_view(self):
        tx = self.current_transaction()
        if tx is None or not tx.manifest.get("files"):
            return
        path = Path(tx.manifest["files"][0]["path"])
        if not path.exists():
            QMessageBox.information(self, "Open File View", "The affected file does not currently exist.")
            return
        browser = self.workspace.active_browser
        if browser is not None:
            browser._open_file_view_path(path, 1)

    def toggle_pin(self):
        tx = self.current_transaction()
        if tx is None:
            return
        self.journal.set_pinned(tx, not tx.pinned)
        self.workspace.history_changed.emit()
