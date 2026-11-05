from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .model import Member
from .search import find_all


@dataclass(frozen=True, slots=True)
class Location:
    module: Path
    scope: str
    category: str
    member_label: str
    cursor_offset: int = 0


@dataclass(frozen=True, slots=True)
class SymbolEntry:
    module: Path
    dotted_module: str
    scope: str
    category: str
    label: str
    line: int

    @property
    def display(self) -> str:
        owner = self.dotted_module
        if self.scope != "<module>":
            owner += "." + self.scope
        return f"{owner}  |  {self.label}  [{self.category}]"


@dataclass(frozen=True, slots=True)
class SearchResult:
    module: Path
    dotted_module: str
    line: int
    column: int
    preview: str

    @property
    def display(self) -> str:
        return f"{self.dotted_module}:{self.line}:{self.column}  {self.preview}"


class NavigationHistory:
    def __init__(self) -> None:
        self._back: list[Location] = []
        self._forward: list[Location] = []
        self.current: Location | None = None

    def visit(self, location: Location) -> None:
        if location == self.current:
            return
        if self.current is not None:
            self._back.append(self.current)
        self.current = location
        self._forward.clear()

    def back(self) -> Location | None:
        if not self._back:
            return None
        if self.current is not None:
            self._forward.append(self.current)
        self.current = self._back.pop()
        return self.current

    def forward(self) -> Location | None:
        if not self._forward:
            return None
        if self.current is not None:
            self._back.append(self.current)
        self.current = self._forward.pop()
        return self.current


def symbols_for_module(path: Path, dotted_name: str, scopes) -> tuple[SymbolEntry, ...]:
    values = []
    for scope in scopes or ():
        for member in scope.members:
            if member.synthetic:
                continue
            values.append(SymbolEntry(path, dotted_name, scope.name, member.category, member.label, member.span.first))
    return tuple(values)


def search_file(path: Path, dotted_name: str, query: str) -> tuple[SearchResult, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        import tokenize
        with path.open("rb") as stream:
            encoding, _ = tokenize.detect_encoding(stream.readline)
        text = path.read_text(encoding=encoding)
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    lines = text.splitlines()
    results = []
    import bisect
    for match in find_all(text, query):
        line_index = bisect.bisect_right(starts, match.start) - 1
        column = match.start - starts[line_index] + 1
        preview = lines[line_index].strip() if line_index < len(lines) else ""
        results.append(SearchResult(path, dotted_name, line_index + 1, column, preview[:160]))
    return tuple(results)
