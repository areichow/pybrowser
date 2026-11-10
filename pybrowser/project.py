from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from .performance import timed

DEFAULT_EXCLUDES = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "build", "dist",
    ".tox", ".nox", "node_modules",
})

@dataclass(frozen=True, slots=True)
class ModuleEntry:
    path: Path
    relative_path: Path
    dotted_name: str
    is_package: bool

@dataclass(frozen=True, slots=True)
class World:
    root: Path
    modules: tuple[ModuleEntry, ...]
    single_file: bool = False


def dotted_module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or root.name


def discover_modules(root: Path, excludes=DEFAULT_EXCLUDES) -> tuple[ModuleEntry, ...]:
    """Discover Python modules without descending into ignored directory trees."""
    root = root.resolve()
    entries: list[ModuleEntry] = []
    with timed("discover_modules", root=root):
        for directory, names, files in os.walk(root, topdown=True):
            names[:] = sorted(
                (name for name in names
                 if name not in excludes and not name.startswith(".")),
                key=str.casefold,
            )
            base = Path(directory)
            for name in files:
                if not name.casefold().endswith(".py"):
                    continue
                path = (base / name).resolve()
                relative = path.relative_to(root)
                entries.append(ModuleEntry(
                    path, relative, dotted_module_name(root, path),
                    name.casefold() == "__init__.py",
                ))
    return tuple(sorted(
        entries,
        key=lambda item: tuple(part.casefold() for part in item.relative_path.parts),
    ))


def open_world(path: Path) -> World:
    path = path.resolve()
    if path.is_file():
        return World(path.parent, (ModuleEntry(path, Path(path.name), path.stem, False),), True)
    if not path.is_dir():
        raise FileNotFoundError(path)
    return World(path, discover_modules(path), False)
