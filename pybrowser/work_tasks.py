from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .code_queries import implementers, senders
from .navigation import search_file


class WorkSignals(QObject):
    started = Signal(int, str)
    progress = Signal(int, int, int, str)
    finished = Signal(int, str, object)
    failed = Signal(int, str, str)


class WorldQueryTask(QRunnable):
    """Run expensive world queries without touching Qt widgets."""

    def __init__(self, task_id, operation, world, argument, signals):
        super().__init__()
        self.task_id = task_id
        self.operation = operation
        self.world = world
        self.argument = argument
        self.signals = signals
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        label = {
            "implementers": f"Finding implementers of {self.argument}",
            "senders": f"Finding senders of {self.argument}",
            "world_search": f"Searching world for {self.argument}",
        }[self.operation]
        self.signals.started.emit(self.task_id, label)
        try:
            if self.operation == "implementers":
                result = implementers(self.world, self.argument, self._progress)
            elif self.operation == "senders":
                result = senders(self.world, self.argument, self._progress)
            else:
                values = []
                total = len(self.world.modules)
                for index, entry in enumerate(self.world.modules, 1):
                    try:
                        values.extend(search_file(entry.path, entry.dotted_name, self.argument))
                    except (OSError, UnicodeError):
                        pass
                    self._progress(index, total, entry.dotted_name)
                result = tuple(values)
            self.signals.finished.emit(self.task_id, self.operation, result)
        except Exception as exc:
            self.signals.failed.emit(self.task_id, self.operation, str(exc))

    def _progress(self, completed, total, detail=""):
        self.signals.progress.emit(self.task_id, completed, total, detail)
