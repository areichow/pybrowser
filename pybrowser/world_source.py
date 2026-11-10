from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .model import Document
from .parser import document_from_stable
from .project import DEFAULT_EXCLUDES, ModuleEntry, dotted_module_name
from .saving import StableFileRead, stable_read


class OverlayConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OverlaySource:
    data: bytes
    encoding: str
    mode: int
    disk_signature: tuple[int, int, str] | None
    transaction_id: str | None = None

    @property
    def signature(self):
        return (-1, len(self.data), hashlib.sha256(self.data).hexdigest())


class WorldSourceStore:
    """One guarded read boundary for disk source and staged overlay source."""

    def __init__(self, world_root: Path, locks=None, on_change=None):
        self.world_root = Path(world_root).resolve()
        self.locks = locks
        self.on_change = on_change
        self._overlay: dict[Path, OverlaySource] = {}

    @staticmethod
    def _path(path: Path) -> Path:
        return Path(path).resolve()

    def visible_signature(self, path: Path):
        path = self._path(path)
        overlay = self._overlay.get(path)
        return overlay.signature if overlay else stable_read(path).signature

    def disk_signature(self, path: Path):
        path = self._path(path)
        overlay = self._overlay.get(path)
        if overlay:
            return overlay.disk_signature
        try:
            return stable_read(path).signature
        except FileNotFoundError:
            return None

    def overlay(self, path: Path):
        return self._overlay.get(self._path(path))

    def stage_bytes(self, path: Path, data: bytes, *, encoding="utf-8", mode=0o644,
                    disk_signature=None, expected_visible_signature=None,
                    transaction_id=None, already_locked=False, restoring=False, notify=True) -> OverlaySource:
        path = self._path(path)
        context = _null_context(path) if already_locked or not self.locks else self.locks.acquire(path)
        with context:
            current = self._overlay.get(path)
            if current is not None:
                current_visible = current.signature
                baseline = current.disk_signature
            else:
                try:
                    disk = stable_read(path)
                    current_visible = disk.signature
                    baseline = disk.signature
                    if mode == 0o644:
                        mode = disk.mode
                except FileNotFoundError:
                    current_visible = None
                    baseline = None
            if expected_visible_signature is not None and expected_visible_signature != current_visible:
                raise OverlayConflictError(f"{path} changed in the staged World. Reload it before saving.")
            if restoring:
                baseline = disk_signature
            if not restoring and disk_signature is not None and baseline is not None and disk_signature != baseline:
                raise OverlayConflictError(f"{path} has a different physical baseline.")
            value = OverlaySource(bytes(data), encoding, int(mode), baseline, transaction_id)
            self._overlay[path] = value
        if notify and self.on_change:
            self.on_change(path)
        return value

    def discard(self, path: Path, notify=True) -> None:
        path = self._path(path)
        existed = self._overlay.pop(path, None) is not None
        if existed and notify and self.on_change:
            self.on_change(path)

    def clear(self) -> None:
        paths = tuple(self._overlay)
        self._overlay.clear()
        if self.on_change:
            for path in paths:
                self.on_change(path)

    def has_overlay(self, path: Path) -> bool:
        return self._path(path) in self._overlay

    def staged_paths(self) -> tuple[Path, ...]:
        return tuple(sorted(self._overlay, key=lambda item: str(item).casefold()))

    def virtual_python_paths(self) -> tuple[Path, ...]:
        return tuple(path for path in self.staged_paths() if path.suffix.casefold() == ".py" and not path.exists())

    def effective_modules(self, modules=()) -> tuple[ModuleEntry, ...]:
        values = {Path(item.path).resolve(): item for item in modules}
        for path in self.virtual_python_paths():
            try:
                relative = path.relative_to(self.world_root)
            except ValueError:
                continue
            if any(part in DEFAULT_EXCLUDES or (part.startswith(".") and part != ".") for part in relative.parts[:-1]):
                continue
            values[path] = ModuleEntry(path, relative, dotted_module_name(self.world_root, path), path.name == "__init__.py")
        return tuple(sorted(values.values(), key=lambda item: tuple(part.casefold() for part in item.relative_path.parts)))

    def exists(self, path: Path) -> bool:
        path = self._path(path)
        return path in self._overlay or path.exists()

    def read_stable(self, path: Path) -> StableFileRead:
        path = self._path(path)
        overlay = self._overlay.get(path)
        if overlay is None:
            return stable_read(path)
        return StableFileRead(overlay.data, overlay.signature, overlay.mode)

    def read_bytes(self, path: Path) -> bytes:
        return self.read_stable(path).data

    def read_text(self, path: Path) -> str:
        return self.read_document(path).text

    def read_document(self, path: Path) -> Document:
        path = self._path(path)
        overlay = self._overlay.get(path)
        stable = self.read_stable(path)
        disk_signature = overlay.disk_signature if overlay else stable.signature
        return document_from_stable(path, stable, disk_signature)

    def source_map(self, paths=None) -> dict[str, bytes]:
        selected = self.staged_paths() if paths is None else tuple(self._path(path) for path in paths)
        return {str(path): self._overlay[path].data for path in selected if path in self._overlay}


class _null_context:
    def __init__(self, value): self.value = value
    def __enter__(self): return self.value
    def __exit__(self, *_args): return False
