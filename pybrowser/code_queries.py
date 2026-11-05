from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass
from pathlib import Path

from .model import Kind
from .parser import build_index


@dataclass(frozen=True, slots=True)
class CodeQueryResult:
    module: Path
    dotted_module: str
    scope: str
    category: str
    label: str
    line: int
    source: str

    @property
    def display(self) -> str:
        owner = self.dotted_module if self.scope == "<module>" else f"{self.dotted_module}.{self.scope}"
        return f"{owner}  |  {self.label}  |  line {self.line}"


def callable_name_from_label(label: str) -> str:
    value = label.strip()
    if value.startswith("async "):
        value = value[6:]
    return value.split("  (", 1)[0].split("(", 1)[0].strip()


def _read(path: Path) -> str:
    raw = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    return raw.decode(encoding)


def _entry_name(world, path: Path) -> str:
    entry = next((item for item in world.modules if item.path.resolve() == path.resolve()), None)
    return entry.dotted_name if entry else path.stem


def implementers(world, name: str) -> tuple[CodeQueryResult, ...]:
    results = []
    for entry in world.modules:
        try:
            text = _read(entry.path)
            scopes = build_index(entry.path, text)
        except (OSError, UnicodeError, ValueError):
            continue
        for scope in scopes:
            for member in scope.members:
                if member.synthetic or member.kind not in {Kind.FUNCTION, Kind.METHOD}:
                    continue
                if callable_name_from_label(member.label) == name:
                    results.append(CodeQueryResult(entry.path, entry.dotted_name, scope.name, member.category, member.label, member.span.first, text[member.span.start:member.span.end]))
    return tuple(results)


def _called_name(call: ast.Call) -> str | None:
    function = call.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


def senders(world, name: str) -> tuple[CodeQueryResult, ...]:
    results = []
    for entry in world.modules:
        try:
            text = _read(entry.path)
            tree = ast.parse(text, filename=str(entry.path))
            scopes = build_index(entry.path, text)
        except (OSError, UnicodeError, SyntaxError, ValueError):
            continue
        call_lines = {node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call) and _called_name(node) == name}
        if not call_lines:
            continue
        for scope in scopes:
            for member in scope.members:
                if member.synthetic:
                    continue
                contained = sorted(line for line in call_lines if member.span.first <= line <= member.span.last)
                if contained:
                    results.append(CodeQueryResult(entry.path, entry.dotted_name, scope.name, member.category, member.label, contained[0], text[member.span.start:member.span.end]))
    return tuple(results)
