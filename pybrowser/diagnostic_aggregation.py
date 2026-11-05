from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

SEVERITY_ORDER = {"error": 3, "warning": 2, "information": 1}
SEVERITY_GLYPH = {"error": "✕", "warning": "▲", "information": "●"}
SEVERITY_COLOR = {"error": "#f07178", "warning": "#dca8ac", "information": "#82aaff"}


@dataclass(frozen=True, slots=True)
class DiagnosticSummary:
    diagnostics: tuple
    errors: int = 0
    warnings: int = 0
    information: int = 0

    @property
    def count(self):
        return len(self.diagnostics)

    @property
    def highest(self):
        if self.errors: return "error"
        if self.warnings: return "warning"
        if self.information: return "information"
        return None

    @property
    def glyph(self):
        if not self.highest: return ""
        suffix = str(self.count) if self.count > 1 else ""
        return SEVERITY_GLYPH[self.highest] + suffix

    @property
    def color(self):
        return SEVERITY_COLOR.get(self.highest)

    def tooltip(self, heading="Diagnostics"):
        if not self.diagnostics:
            return f"{heading}\nNo diagnostic concerns"
        lines = [heading, "", f"{self.errors} error(s), {self.warnings} warning(s), {self.information} information message(s)"]
        for diagnostic in self.diagnostics[:12]:
            lines.append(f"{SEVERITY_GLYPH.get(diagnostic.severity, '•')} line {diagnostic.line}: {diagnostic.rule}: {diagnostic.message}")
        if len(self.diagnostics) > 12:
            lines.append(f"…and {len(self.diagnostics) - 12} more")
        return "\n".join(lines)


def summarize(diagnostics):
    values = tuple(diagnostics)
    return DiagnosticSummary(
        values,
        sum(item.severity == "error" for item in values),
        sum(item.severity == "warning" for item in values),
        sum(item.severity == "information" for item in values),
    )


def decorate(label, summary):
    return f"{summary.glyph} {label}" if summary.count else label


class DiagnosticAggregation:
    def __init__(self, semantic_modules=None, documents=None):
        self.semantic_modules = semantic_modules or {}
        self.documents = documents or {}

    def world(self):
        return summarize(d for module in self.semantic_modules.values() for d in module.diagnostics)

    def module(self, path: Path):
        module = self.semantic_modules.get(Path(path).resolve())
        return summarize(module.diagnostics if module else ())

    def scope(self, path: Path, scope_name: str, scopes):
        lines = []
        scope = next((item for item in scopes if item.name == scope_name), None)
        if scope and scope.members:
            lines = [(min(m.span.first for m in scope.members), max(m.span.last for m in scope.members))]
        module = self.semantic_modules.get(Path(path).resolve())
        if not module: return summarize(())
        values = [d for d in module.diagnostics if any(first <= d.line <= last for first, last in lines)]
        return summarize(values)

    def member(self, path: Path, member):
        module = self.semantic_modules.get(Path(path).resolve())
        if not module: return summarize(())
        return summarize(d for d in module.diagnostics if member.span.first <= d.line <= member.span.last)

    def category(self, path: Path, scope, category: str):
        module = self.semantic_modules.get(Path(path).resolve())
        if not module: return summarize(())
        members = [m for m in scope.members if not m.synthetic and m.category == category]
        values = [d for d in module.diagnostics if any(m.span.first <= d.line <= m.span.last for m in members)]
        # Category metadata diagnostics occur outside editable Member spans.
        for diagnostic in module.diagnostics:
            if diagnostic.rule not in {"unused-category-metadata", "duplicate-category-directive"}:
                continue
            match = re.search(r"Category '([^']+)'", diagnostic.message)
            if match and match.group(1).strip().casefold() == category.strip().casefold() and diagnostic not in values:
                values.append(diagnostic)
        return summarize(values)
