from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .model import Scope
from .project import ModuleEntry
from .semantic import SemanticModule


@dataclass(frozen=True, slots=True)
class ModuleIndexResult:
    path: Path
    generation: int
    scopes: tuple[Scope, ...] | None
    semantic: SemanticModule | None = None
    error: str | None = None


class IndexSignals(QObject):
    # Batches significantly reduce queued Qt events for large repositories.
    results = Signal(object)
    progress = Signal(int, int, int)
    finished = Signal(int)


class IndexWorldTask(QRunnable):
    """Coordinate process-based parsing without running LibCST on the UI process."""

    BATCH_SIZE = 24

    def __init__(self, modules, generation, signals, cancelled, max_workers=None):
        super().__init__()
        self.modules = tuple(modules)
        self.generation = generation
        self.signals = signals
        self.cancelled = cancelled
        cpu_count = os.cpu_count() or 2
        self.max_workers = max_workers or max(1, min(4, cpu_count - 1))
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        total = len(self.modules)
        completed = 0
        batch = []
        executor = None
        try:
            # Import in the worker thread so child-process startup does not add
            # work to the Qt event thread.
            from .index_worker import index_module
            executor = ProcessPoolExecutor(max_workers=min(self.max_workers, max(1, total)))
            futures = {executor.submit(index_module, str(entry.path)): entry.path for entry in self.modules}
            for future in as_completed(futures):
                if self.cancelled.is_set():
                    break
                path = futures[future]
                try:
                    result_path, scopes, semantic, error = future.result()
                except BaseException as exc:
                    result_path, scopes, semantic, error = path, None, None, str(exc)
                batch.append(ModuleIndexResult(Path(result_path), self.generation, scopes, semantic, error))
                completed += 1
                if len(batch) >= self.BATCH_SIZE:
                    self.signals.results.emit(tuple(batch))
                    batch.clear()
                    self.signals.progress.emit(self.generation, completed, total)
            if batch and not self.cancelled.is_set():
                self.signals.results.emit(tuple(batch))
                self.signals.progress.emit(self.generation, completed, total)
        finally:
            if executor is not None:
                # A superseded world must not block while old parse processes finish.
                executor.shutdown(wait=not self.cancelled.is_set(), cancel_futures=True)
            self.signals.finished.emit(self.generation)
