from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .model import Document
from .parser import document_from_stable
from .saving import StableFileRead, stable_read


@dataclass(frozen=True, slots=True)
class OverlaySource:
    data: bytes
    encoding: str
    mode: int
    disk_signature: tuple[int, int, str] | None


class WorldSourceStore:
    """One read boundary for disk source and future staged overlay source."""

    def __init__(self, world_root: Path):
        self.world_root = Path(world_root).resolve()
        self._overlay: dict[Path, OverlaySource] = {}

    @staticmethod
    def _path(path: Path) -> Path:
        return Path(path).resolve()

    def stage_bytes(self, path: Path, data: bytes, *, encoding="utf-8", mode=0o644,
                    disk_signature=None) -> None:
        path = self._path(path)
        self._overlay[path] = OverlaySource(bytes(data), encoding, int(mode), disk_signature)

    def discard(self, path: Path) -> None:
        self._overlay.pop(self._path(path), None)

    def clear(self) -> None:
        self._overlay.clear()

    def has_overlay(self, path: Path) -> bool:
        return self._path(path) in self._overlay

    def staged_paths(self) -> tuple[Path, ...]:
        return tuple(sorted(self._overlay, key=lambda item: str(item).casefold()))

    def exists(self, path: Path) -> bool:
        path = self._path(path)
        return path in self._overlay or path.exists()

    def read_stable(self, path: Path) -> StableFileRead:
        path = self._path(path)
        overlay = self._overlay.get(path)
        if overlay is None:
            return stable_read(path)
        digest = hashlib.sha256(overlay.data).hexdigest()
        # A virtual signature cannot collide with a normal nanosecond mtime in practice.
        return StableFileRead(overlay.data, (-1, len(overlay.data), digest), overlay.mode)

    def read_bytes(self, path: Path) -> bytes:
        return self.read_stable(path).data

    def read_text(self, path: Path) -> str:
        return self.read_document(path).text

    def read_document(self, path: Path) -> Document:
        path = self._path(path)
        return document_from_stable(path, self.read_stable(path))

    def source_map(self, paths=None) -> dict[str, bytes]:
        selected = self.staged_paths() if paths is None else tuple(self._path(path) for path in paths)
        return {str(path): self._overlay[path].data for path in selected if path in self._overlay}
