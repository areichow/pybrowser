from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .model import Scope
from .parser import ParseError, read_document
from .project import ModuleEntry
from .semantic import SemanticModule, analyze_source


@dataclass(frozen=True, slots=True)
class ModuleIndexResult:
    path: Path
    generation: int
    scopes: tuple[Scope, ...] | None
    semantic: SemanticModule | None = None
    error: str | None = None


class IndexSignals(QObject):
    result = Signal(object)
    progress = Signal(int, int, int)
    finished = Signal(int)


class IndexWorldTask(QRunnable):
    """Parse a snapshot of modules without touching Qt widgets."""

    def __init__(
        self,
        modules: tuple[ModuleEntry, ...],
        generation: int,
        signals: IndexSignals,
        cancelled: Event,
    ) -> None:
        super().__init__()
        self.modules = modules
        self.generation = generation
        self.signals = signals
        self.cancelled = cancelled
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        total = len(self.modules)
        completed = 0
        for entry in self.modules:
            if self.cancelled.is_set():
                break
            try:
                document = read_document(entry.path)
                semantic = analyze_source(entry.path, document.text)
                result = ModuleIndexResult(entry.path, self.generation, document.scopes, semantic)
            except (OSError, UnicodeError, ParseError, SyntaxError) as exc:
                result = ModuleIndexResult(entry.path, self.generation, None, None, str(exc))
            self.signals.result.emit(result)
            completed += 1
            self.signals.progress.emit(self.generation, completed, total)
        self.signals.finished.emit(self.generation)
