from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .model import Scope


@dataclass(frozen=True, slots=True)
class CachedModule:
    signature: tuple[int, int, str] | tuple[int, int]
    scopes: tuple[Scope, ...] | None
    error: str | None = None


class ModuleIndexCache:
    def __init__(self, source_store=None) -> None:
        self.source_store = source_store
        self._items: dict[Path, CachedModule] = {}

    def signature(self, path: Path):
        path = Path(path).resolve()
        if self.source_store is not None:
            overlay = self.source_store.overlay(path)
            if overlay is not None:
                return overlay.signature
        stat = path.stat()
        # Cache identity is intentionally cheap. Source writes and recovery still
        # use stable SHA-256 signatures at every integrity boundary.
        return stat.st_mtime_ns, stat.st_size

    def set_source_store(self, source_store):
        self.source_store = source_store
        self.clear()

    def put(self, path: Path, scopes: tuple[Scope, ...] | None, error: str | None = None) -> None:
        path = path.resolve()
        try:
            signature = self.signature(path)
        except OSError:
            self._items.pop(path, None)
            return
        self._items[path] = CachedModule(signature, scopes, error)

    def get(self, path: Path) -> CachedModule | None:
        path = path.resolve()
        item = self._items.get(path)
        if item is None:
            return None
        try:
            if item.signature != self.signature(path):
                self._items.pop(path, None)
                return None
        except OSError:
            self._items.pop(path, None)
            return None
        return item

    def retain(self, paths: set[Path]) -> None:
        resolved = {path.resolve() for path in paths}
        self._items = {path: item for path, item in self._items.items() if path in resolved}

    def invalidate(self, path: Path) -> None:
        self._items.pop(path.resolve(), None)

    def clear(self) -> None:
        self._items.clear()
