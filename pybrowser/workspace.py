from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication

from .recovery import RecoveryConflictError, RecoveryJournal


class WorkspaceUndoError(RuntimeError):
    def __init__(self, message, windows=(), conflict=None):
        super().__init__(message)
        self.windows = tuple(windows)
        self.conflict = conflict


class Workspace(QObject):
    """Coordinates windows that operate on the same file/folder World."""

    file_changed = Signal(object, object)
    world_changed = Signal(object)
    windows_changed = Signal()
    history_changed = Signal()

    def __init__(self, world=None, parent=None):
        super().__init__(parent)
        self.world = world
        self.windows = []
        self.active_browser = None
        self.journal = None

    def set_world(self, world):
        self.world = world
        settings = QSettings("PyBrowser", "PyBrowser")
        self.journal = RecoveryJournal(
            world.root,
            max_transactions=settings.value("recovery/maxTransactions", 200, int),
            min_days=settings.value("recovery/minDays", 30, int),
            max_megabytes=settings.value("recovery/maxMegabytes", 500, int),
        )
        self.journal.on_change = self.history_changed.emit
        self.world_changed.emit(world)
        self.history_changed.emit()

    def announce_file_changed(self, path: Path, origin=None):
        self.file_changed.emit(Path(path).resolve(), origin)

    def register(self, window, kind="window"):
        if window in self.windows:
            return
        window.window_kind = kind
        self.windows.append(window)
        if kind == "browser":
            self.active_browser = window
        window.destroyed.connect(lambda: self._remove(window))
        self.windows_changed.emit()

    def open_windows(self):
        return [window for window in self.windows if window is not None and not getattr(window, "isHidden", lambda: True)()]

    def browser_count(self):
        return sum(1 for window in self.open_windows() if getattr(window, "window_kind", "") == "browser")

    def activate_window(self, window):
        if window is None:
            return
        window.showNormal()
        window.raise_()
        window.activateWindow()
        if getattr(window, "window_kind", "") == "browser":
            self.active_browser = window

    def quit_application(self):
        QApplication.instance().closeAllWindows()

    def request_class_browser(self, class_name):
        if self.active_browser is not None:
            self.active_browser.open_browser_on_class(class_name)

    @staticmethod
    def _window_modified_path(window):
        kind = getattr(window, "window_kind", "")
        if kind == "browser":
            document = getattr(window, "doc", None)
            editor = getattr(window, "editor", None)
            if document is not None and editor is not None and editor.document().isModified():
                return document.path.resolve()
        elif kind == "file-view":
            editor = getattr(window, "editor", None)
            path = getattr(window, "path", None)
            if path is not None and editor is not None and editor.document().isModified():
                return Path(path).resolve()
        elif kind == "query":
            editor = getattr(window, "preview", None)
            document = getattr(window, "current_document", None)
            if document is not None and editor is not None and editor.document().isModified():
                return document.path.resolve()
        return None

    def unsaved_windows_for(self, paths):
        affected = {Path(path).resolve() for path in paths}
        return tuple(window for window in self.open_windows()
                     if self._window_modified_path(window) in affected)

    def perform_history_action(self, direction, transaction=None):
        if not self.journal:
            raise WorkspaceUndoError("Open a World before using Structural Undo or Redo.")
        transaction = transaction or (self.journal.latest_undo() if direction == "undo" else self.journal.latest_redo())
        if transaction is None:
            raise WorkspaceUndoError(f"There is no transaction available to {direction}.")
        paths = [Path(item.get("absolute_path") or item.get("path", "")).resolve()
                 for item in transaction.manifest.get("files", [])]
        modified = self.unsaved_windows_for(paths)
        if modified:
            names = ", ".join(window.windowTitle().replace("[*]", "").strip() for window in modified)
            raise WorkspaceUndoError(
                f"Cannot {direction} while affected windows have unsaved edits: {names}", modified,
            )
        try:
            result, changed_paths = self.journal.apply_transaction(transaction, direction)
        except RecoveryConflictError as exc:
            raise WorkspaceUndoError(str(exc), conflict=exc) from exc

        for path in changed_paths:
            self.announce_file_changed(path, None)
        location = result.manifest.get("location_before" if direction == "undo" else "location_after")
        if self.active_browser is not None and location:
            self.active_browser.restore_journal_location(location)
        self.history_changed.emit()
        return result, changed_paths

    def _remove(self, window):
        if window in self.windows:
            self.windows.remove(window)
        if self.active_browser is window:
            self.active_browser = next((item for item in reversed(self.windows)
                                        if getattr(item, "window_kind", "") == "browser"), None)
        self.windows_changed.emit()
