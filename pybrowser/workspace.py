from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import QObject, Signal


class Workspace(QObject):
    """Coordinates windows that operate on the same file/folder world."""
    file_changed = Signal(object, object)  # Path, originating QObject
    world_changed = Signal(object)

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

    def register(self, window):
        self.windows.append(window)
        if hasattr(window, "open_browser_on_class"):
            self.active_browser = window
        window.destroyed.connect(lambda: self._remove(window))

    def request_class_browser(self, class_name):
        if self.active_browser is not None:
            self.active_browser.open_browser_on_class(class_name)

    def _remove(self, window):
        if window in self.windows:
            self.windows.remove(window)
