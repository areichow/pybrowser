from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .semantic import SemanticModule, SemanticReference, read_source
from .parser import build_index


@dataclass(frozen=True, slots=True)
class ReferenceResult:
    module: Path
    dotted_module: str
    scope: str
    category: str
    label: str
    line: int
    column: int
    reference_kind: str
    source: str

    @property
    def display(self):
        owner = self.dotted_module if self.scope == "<module>" else f"{self.dotted_module}.{self.scope}"
        return f"{owner} | {self.reference_kind} | {self.label} | line {self.line}:{self.column}"


def references_in_world(world, semantic_modules: dict[Path, SemanticModule], name: str, kinds=None):
    allowed = set(kinds or {"read", "write", "call", "import", "base", "decorator", "annotation", "delete"})
    results = []
    for entry in world.modules:
        semantic = semantic_modules.get(entry.path.resolve())
        if semantic is None:
            continue
        matching = [ref for ref in semantic.references if ref.name == name and ref.kind in allowed]
        if not matching:
            continue
        try:
            text = read_source(entry.path)
            scopes = build_index(entry.path, text)
        except (OSError, UnicodeError, ValueError):
            continue
        for reference in matching:
            containing = []
            for scope in scopes:
                for member in scope.members:
                    if not member.synthetic and member.span.first <= reference.line <= member.span.last:
                        containing.append((member.span.last - member.span.first, scope, member))
            if containing:
                _size, scope, member = min(containing, key=lambda value: value[0])
                source = text[member.span.start:member.span.end]
                results.append(ReferenceResult(entry.path, entry.dotted_name, scope.name, member.category, member.label, reference.line, reference.column, reference.kind, source))
            else:
                line_text = text.splitlines()[reference.line - 1] if reference.line <= len(text.splitlines()) else ""
                results.append(ReferenceResult(entry.path, entry.dotted_name, "<module>", "Executable Code", f"line {reference.line}", reference.line, reference.column, reference.kind, line_text))
    return tuple(results)
