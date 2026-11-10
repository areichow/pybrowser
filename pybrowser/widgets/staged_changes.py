from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ..saving import stable_read
from ..source_write_service import SourceConflictError
from ..windowing import install_window_commands


@dataclass(frozen=True, slots=True)
class StagedChange:
    path: Path
    transaction: object
    disk_signature: tuple[int, int, str] | None
    before_exists: bool
    conflict: bool
    conflict_detail: str

    @property
    def kind(self):
        return "existing file" if self.before_exists else "virtual new file"


class StagedChangesWindow(QMainWindow):
    """Modeless review and disposition window for active Manual Commit overlays."""

    def __init__(self, workspace, parent=None):
        super().__init__(None)
        self.workspace = workspace
        self.workspace.register(self, "staged-changes")
        self.changes: list[StagedChange] = []
        self.setWindowTitle("Staged Changes")
        self.resize(1120, 760)

        self.summary = QLabel()
        self.list = QListWidget()
        self.detail = QLabel("Select a staged file")
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.diff = QPlainTextEdit(); self.diff.setReadOnly(True)

        right = QWidget(); right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.detail); right_layout.addWidget(self.diff, 1)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.list); split.addWidget(right); split.setSizes([390, 730])

        self.commit_selected_button = QPushButton("Commit Selected")
        self.commit_selected_button.clicked.connect(self.commit_selected)
        self.abandon_selected_button = QPushButton("Abandon Selected...")
        self.abandon_selected_button.clicked.connect(self.abandon_selected)
        self.open_button = QPushButton("Open Staged Source")
        self.open_button.clicked.connect(self.open_selected)
        commit_all = QPushButton("Commit All")
        commit_all.clicked.connect(self.commit_all)
        abandon_all = QPushButton("Abandon All...")
        abandon_all.clicked.connect(self.abandon_all)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)

        buttons = QHBoxLayout()
        for button in (self.commit_selected_button, self.abandon_selected_button,
                       self.open_button, commit_all, abandon_all):
            buttons.addWidget(button)
        buttons.addStretch(1); buttons.addWidget(refresh)

        central = QWidget(); layout = QVBoxLayout(central)
        layout.addWidget(self.summary); layout.addWidget(split, 1); layout.addLayout(buttons)
        self.setCentralWidget(central)
        file_menu = self.menuBar().addMenu("&File")
        install_window_commands(self, workspace, file_menu)

        self.list.currentRowChanged.connect(self._selected)
        self.workspace.history_changed.connect(self.refresh)
        self.workspace.world_changed.connect(lambda _world: self.refresh())
        self.refresh()

    @staticmethod
    def _conflict(path, disk_signature, before_exists):
        if before_exists:
            try:
                current = stable_read(path).signature
            except OSError as exc:
                return True, f"Physical baseline cannot be read: {exc}"
            if current != disk_signature:
                return True, "Physical file differs from the staged baseline"
            return False, "Physical file still matches the staged baseline"
        if path.exists():
            return True, "A physical file now exists at this virtual-file path"
        return False, "Virtual target is still absent from disk"

    def _load_changes(self):
        values = []
        if not self.workspace.journal:
            return values
        for path, transaction, disk_signature in self.workspace.journal.active_overlays():
            item = transaction.files[0]
            before_exists = item.get("before_exists", True)
            conflict, detail = self._conflict(path, disk_signature, before_exists)
            values.append(StagedChange(path, transaction, disk_signature,
                                       before_exists, conflict, detail))
        return values

    def refresh(self):
        selected_path = self.current_change().path if self.current_change() else None
        self.changes = self._load_changes()
        self.list.clear()
        selected_row = 0
        conflicts = 0
        root = self.workspace.world.root if self.workspace.world else None
        for row, change in enumerate(self.changes):
            try:
                display_path = change.path.relative_to(root).as_posix() if root else str(change.path)
            except ValueError:
                display_path = str(change.path)
            marker = "CONFLICT  " if change.conflict else "STAGED  "
            item = self.list.addItem(marker + display_path)
            list_item = self.list.item(self.list.count() - 1)
            if change.conflict:
                conflicts += 1
                list_item.setForeground(QColor("#f07178"))
            else:
                list_item.setForeground(QColor("#82aaff"))
            if change.path == selected_path:
                selected_row = row
        self.summary.setText(
            f"{len(self.changes)} staged file(s), {conflicts} conflict(s). "
            "Physical source is unchanged until Commit."
        )
        if self.changes:
            self.list.setCurrentRow(selected_row)
        else:
            self.detail.setText("No staged changes for this World")
            self.diff.clear()
            self._set_selected_actions(False, False)

    def current_change(self):
        row = self.list.currentRow()
        return self.changes[row] if 0 <= row < len(self.changes) else None

    def _set_selected_actions(self, selected, conflict):
        self.commit_selected_button.setEnabled(selected and not conflict)
        self.abandon_selected_button.setEnabled(selected)
        self.open_button.setEnabled(selected)

    def _selected(self, _row):
        change = self.current_change()
        if change is None:
            self._set_selected_actions(False, False)
            return
        tx = change.transaction
        item = tx.files[0]
        self.detail.setText("\n".join((
            str(change.path),
            f"State: {'CONFLICT' if change.conflict else 'ready to commit'}",
            f"Kind: {change.kind}",
            f"Operation: {tx.operation}",
            f"Description: {tx.description}",
            f"Staged at: {tx.timestamp}",
            f"Transaction: {tx.transaction_id}",
            f"Disk check: {change.conflict_detail}",
            f"Before: {item.get('before_sha256')}",
            f"Staged: {item.get('after_sha256')}",
        )))
        self._set_selected_actions(True, change.conflict)
        try:
            encoding = item.get("encoding") or "utf-8"
            before = self.workspace.journal.snapshot_path(tx, "before").read_text(
                encoding=encoding, errors="replace").splitlines()
            after = self.workspace.journal.snapshot_path(tx, "after").read_text(
                encoding=encoding, errors="replace").splitlines()
            relative = item.get("relative_path") or change.path.name
            diff = difflib.unified_diff(before, after, fromfile="disk/" + relative,
                                        tofile="staged/" + relative, lineterm="")
            self.diff.setPlainText("\n".join(diff) or "No textual differences")
        except OSError as exc:
            self.diff.setPlainText(f"Snapshot unavailable: {exc}")

    def commit_selected(self):
        change = self.current_change()
        if change is None:
            return
        try:
            self.workspace.write_service.commit_staged(change.path, self)
            self.statusBar().showMessage(f"Committed {change.path.name} to disk", 6000)
        except (SourceConflictError, OSError) as exc:
            QMessageBox.warning(self, "Commit Refused", str(exc))
        self.refresh()

    def abandon_selected(self):
        change = self.current_change()
        if change is None:
            return
        answer = QMessageBox.question(
            self, "Abandon Staged Change?",
            f"Abandon the staged change for {change.path}? The physical file will remain unchanged.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.workspace.write_service.discard_staged(change.path, self)
        self.statusBar().showMessage(f"Abandoned staged change for {change.path.name}", 6000)
        self.refresh()

    def commit_all(self):
        if not self.changes:
            return
        try:
            self.workspace.commit_all_staged(self)
            self.statusBar().showMessage("Committed all staged changes to disk", 6000)
        except (SourceConflictError, OSError) as exc:
            QMessageBox.warning(self, "Commit All Refused", str(exc))
        self.refresh()

    def abandon_all(self):
        if not self.changes:
            return
        answer = QMessageBox.question(
            self, "Abandon All Staged Changes?",
            f"Abandon {len(self.changes)} staged file change(s)? Physical files will remain unchanged.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.workspace.discard_all_staged(self)
        self.statusBar().showMessage("Abandoned all staged changes", 6000)
        self.refresh()

    def open_selected(self):
        change = self.current_change()
        browser = self.workspace.active_browser
        if change is not None and browser is not None:
            browser._open_file_view_path(change.path, 1)
