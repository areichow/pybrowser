from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from ..recovery import RecoveryConflictError
from ..windowing import install_window_commands


class StagedCommitRecoveryWindow(QMainWindow):
    """Explicit recovery for interrupted staged commit batches."""

    def __init__(self, workspace, parent=None):
        super().__init__(None)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.workspace = workspace
        self.workspace.register(self, "staged-commit-recovery")
        self.batches = []
        self.setWindowTitle("Staged Commit Recovery")
        self.resize(940, 620)
        self.summary = QLabel()
        self.list = QListWidget()
        self.detail = QLabel(); self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.rollback_button = QPushButton("Restore Entire Before State")
        self.rollback_button.clicked.connect(lambda: self.resolve("rollback"))
        self.forward_button = QPushButton("Complete Entire Transaction")
        self.forward_button.clicked.connect(lambda: self.resolve("forward"))
        self.review_button = QPushButton("Mark for Manual Review")
        self.review_button.clicked.connect(lambda: self.resolve("review"))
        refresh = QPushButton("Refresh"); refresh.clicked.connect(self.refresh)
        buttons = QHBoxLayout()
        for button in (self.rollback_button, self.forward_button, self.review_button):
            buttons.addWidget(button)
        buttons.addStretch(1); buttons.addWidget(refresh)
        central = QWidget(); layout = QVBoxLayout(central)
        layout.addWidget(self.summary); layout.addWidget(self.list, 1); layout.addWidget(self.detail); layout.addLayout(buttons)
        self.setCentralWidget(central)
        file_menu = self.menuBar().addMenu("&File")
        install_window_commands(self, workspace, file_menu)
        self.list.currentRowChanged.connect(self.selected)
        self.workspace.history_changed.connect(self.refresh)
        self.refresh()

    def current_batch(self):
        row = self.list.currentRow()
        return self.batches[row] if 0 <= row < len(self.batches) else None

    def refresh(self):
        selected = self.current_batch().batch_id if self.current_batch() else None
        self.batches = list(self.workspace.journal.incomplete_staged_commit_batches())
        self.list.clear(); selected_row = 0
        for row, batch in enumerate(self.batches):
            states = self.workspace.journal.inspect_staged_commit_batch(batch)
            state_values = {state for _path, state in states}
            classification = "foreign" if "current differs from both" in state_values else (
                "all-before" if state_values == {"current equals before"} else
                "all-after" if state_values == {"current equals after"} else "mixed"
            )
            self.list.addItem(f"{batch.started_at[:19]}  [{batch.status} / {classification}]  {len(batch.files)} file(s)")
            item = self.list.item(self.list.count() - 1)
            item.setForeground(QColor("#f07178" if classification == "foreign" else "#ffd166"))
            if batch.batch_id == selected: selected_row = row
        self.summary.setText(f"{len(self.batches)} interrupted staged commit batch(es). Active overlays remain available until recovery completes.")
        if self.batches: self.list.setCurrentRow(selected_row)
        else:
            self.detail.setText("No interrupted staged commit batches")
            for button in (self.rollback_button, self.forward_button, self.review_button): button.setEnabled(False)

    def selected(self, _row):
        batch = self.current_batch()
        if batch is None: return
        states = self.workspace.journal.inspect_staged_commit_batch(batch)
        foreign = any(state == "current differs from both" for _path, state in states)
        lines = [f"Batch: {batch.batch_id}", f"Status: {batch.status}", f"Started: {batch.started_at}", ""]
        for item, (path, state) in zip(batch.files, states):
            lines.extend((str(path), f"Physical state: {state}", f"Progress: {item.progress}", f"Staged transaction: {item.transaction_id}", ""))
        if batch.error: lines.extend(("Recorded error:", batch.error))
        self.detail.setText("\n".join(lines))
        self.rollback_button.setEnabled(not foreign)
        self.forward_button.setEnabled(not foreign)
        self.review_button.setEnabled(True)

    def resolve(self, action):
        batch = self.current_batch()
        if batch is None: return
        try:
            result = self.workspace.journal.resolve_staged_commit_batch(batch, action)
            if action == "forward":
                for item in batch.files:
                    self.workspace.source_store.discard(item.path, notify=False)
                    self.workspace.announce_file_changed(item.path, self)
                warnings = getattr(result, "warnings", ())
                if warnings: QMessageBox.warning(self, "Recovered with warning", "\n".join(warnings))
            elif action == "rollback":
                for item in batch.files:
                    self.workspace.announce_file_changed(item.path, self)
            self.statusBar().showMessage(f"Recovery action completed: {action}", 6000)
        except (RecoveryConflictError, OSError) as exc:
            QMessageBox.warning(self, "Recovery Action Refused", str(exc))
        self.refresh()
