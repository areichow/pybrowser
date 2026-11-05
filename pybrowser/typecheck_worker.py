from PySide6.QtCore import QObject, QRunnable, Signal, Slot
from .typecheck import run_type_check


class TypeCheckSignals(QObject):
    finished = Signal(object)


class TypeCheckTask(QRunnable):
    def __init__(self, target, preferred, executable, python_path, signals):
        super().__init__()
        self.target = target
        self.preferred = preferred
        self.executable = executable
        self.python_path = python_path
        self.signals = signals

    @Slot()
    def run(self):
        result = run_type_check(self.target, self.preferred, self.executable, self.python_path)
        self.signals.finished.emit(result)
