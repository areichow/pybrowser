from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


class Workspace(QObject):
    """Coordinates windows that operate on the same file/folder world."""
    file_changed = Signal(object, object)
    world_changed = Signal(object)
    windows_changed = Signal()

    def __init__(self, world=None, parent=None):
        super().__init__(parent)
        self.world = world
        self.windows = []
        self.active_browser = None

    def set_world(self, world):
        self.world = world
        self.world_changed.emit(world)

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

    def _remove(self, window):
        if window in self.windows:
            self.windows.remove(window)
        if self.active_browser is window:
            self.active_browser = next((item for item in reversed(self.windows) if getattr(item, "window_kind", "") == "browser"), None)
        self.windows_changed.emit()
