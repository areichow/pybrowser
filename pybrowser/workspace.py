from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QCoreApplication, QSettings, Signal
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from .recovery import RecoveryConflictError, RecoveryJournal
from .source_write_service import SourceWriteService, WriteMode
from .world_source import WorldSourceStore
from .project import World


class WorkspaceStagingError(RuntimeError):
    def __init__(self, message, windows=()):
        super().__init__(message)
        self.windows = tuple(windows)


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
        self.write_service = None
        self.source_store = None

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
        self.source_store = WorldSourceStore(world.root, self.journal.locks, self._overlay_changed)
        self._restore_active_overlays()
        self.write_service = SourceWriteService(
            self.journal, self.announce_file_changed, source_store=self.source_store,
            write_mode=settings.value("source/writeMode", WriteMode.AUTO_COMMIT.value, str),
        )
        self.world_changed.emit(world)
        self.history_changed.emit()

    def _restore_active_overlays(self):
        for path, transaction, disk_signature in self.journal.active_overlays():
            item = transaction.files[0]
            after = self.journal.snapshot_path(transaction, "after")
            if transaction.damaged or not after.exists():
                continue
            data = after.read_bytes()
            if __import__("hashlib").sha256(data).hexdigest() != item.get("after_sha256"):
                continue
            self.source_store.stage_bytes(
                path, data, encoding=item.get("encoding") or "utf-8",
                mode=item.get("mode") or 0o644, disk_signature=disk_signature,
                transaction_id=transaction.transaction_id, restoring=True, notify=False,
            )

    def _overlay_changed(self, path):
        self.file_changed.emit(Path(path).resolve(), None)
        self.world_changed.emit(self.effective_world())

    def staged_paths(self):
        return self.source_store.staged_paths() if self.source_store else ()

    def set_write_mode(self, mode):
        mode = WriteMode(mode)
        QSettings("PyBrowser", "PyBrowser").setValue("source/writeMode", mode.value)
        if self.write_service:
            self.write_service.write_mode = mode

    def _ensure_staging_paths_are_saved(self, paths, action):
        modified = self.unsaved_windows_for(paths)
        if modified:
            names = ", ".join(
                window.windowTitle().replace("[*]", "").strip() for window in modified
            )
            raise WorkspaceStagingError(
                f"Cannot {action} while affected windows have unsaved edits: {names}",
                modified,
            )

    def commit_staged_path(self, path, origin=None):
        path = Path(path).resolve()
        self._ensure_staging_paths_are_saved((path,), "commit staged changes")
        return self.write_service.commit_staged(path, origin)

    def commit_all_staged(self, origin=None):
        paths = self.staged_paths()
        self._ensure_staging_paths_are_saved(paths, "commit staged changes")
        return self.write_service.commit_all_staged(origin) if self.write_service else ()

    def discard_staged_path(self, path, origin=None):
        path = Path(path).resolve()
        self._ensure_staging_paths_are_saved((path,), "abandon staged changes")
        return self.write_service.discard_staged(path, origin)

    def discard_all_staged(self, origin=None):
        paths = self.staged_paths()
        self._ensure_staging_paths_are_saved(paths, "abandon staged changes")
        return self.write_service.discard_all_staged(origin) if self.write_service else ()

    def effective_world(self):
        if self.world is None or self.source_store is None:
            return self.world
        modules = self.source_store.effective_modules(self.world.modules)
        return World(self.world.root, modules, self.world.single_file)

    def read_document(self, path):
        if self.source_store is None:
            raise RuntimeError("Open a World before reading source")
        return self.source_store.read_document(path)

    def announce_file_changed(self, path: Path, origin=None):
        path = Path(path).resolve()
        self.file_changed.emit(path, origin)
        if path.suffix.casefold() == ".py":
            self.world_changed.emit(self.effective_world())

    @staticmethod
    def _valid_window(window):
        try:
            return window is not None and isValid(window)
        except RuntimeError:
            return False

    def _compact_windows(self):
        """Drop deleted Shiboken wrappers without invoking a Qt method on them."""
        self.windows = [window for window in self.windows if self._valid_window(window)]
        if not self._valid_window(self.active_browser):
            self.active_browser = next(
                (window for window in reversed(self.windows)
                 if getattr(window, "window_kind", "") == "browser"),
                None,
            )

    def register(self, window, kind="window"):
        self._compact_windows()
        if window in self.windows:
            return
        window.window_kind = kind
        self.windows.append(window)
        if kind == "browser":
            self.active_browser = window
        window.destroyed.connect(self._window_destroyed)
        if not QCoreApplication.closingDown():
            self.windows_changed.emit()

    def open_windows(self):
        self._compact_windows()
        values = []
        for window in self.windows:
            try:
                if not window.isHidden():
                    values.append(window)
            except RuntimeError:
                continue
        if len(values) != len(self.windows):
            self._compact_windows()
        return values

    def browser_count(self):
        return sum(1 for window in self.open_windows() if getattr(window, "window_kind", "") == "browser")

    def activate_window(self, window):
        if not self._valid_window(window):
            self._compact_windows()
            return
        try:
            window.showNormal()
            window.raise_()
            window.activateWindow()
            if getattr(window, "window_kind", "") == "browser":
                self.active_browser = window
        except RuntimeError:
            self._compact_windows()

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

    def unregister(self, window, emit=True):
        self.windows = [item for item in self.windows
                        if item is not window and self._valid_window(item)]
        if self.active_browser is window or not self._valid_window(self.active_browser):
            self.active_browser = next(
                (item for item in reversed(self.windows)
                 if getattr(item, "window_kind", "") == "browser"),
                None,
            )
        if emit and not QCoreApplication.closingDown():
            self.windows_changed.emit()

    def _window_destroyed(self, _destroyed_object=None):
        # The QObject supplied by destroyed() is not guaranteed to be identical
        # to the original Python wrapper. Compact by Shiboken validity instead.
        self._compact_windows()
        if not QCoreApplication.closingDown():
            self.windows_changed.emit()
