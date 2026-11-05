from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FileSearchHit:
    start: int
    end: int
    line: int
    column: int
    preview: str

    @property
    def display(self):
        return f"Line {self.line}, Col {self.column}: {self.preview}"


def compile_pattern(query, match_case=False, whole_word=False):
    if not query:
        return None
    value = re.escape(query)
    if whole_word:
        value = r"(?<!\w)" + value + r"(?!\w)"
    return re.compile(value, 0 if match_case else re.IGNORECASE)


def find_hits(text, query, match_case=False, whole_word=False):
    pattern = compile_pattern(query, match_case, whole_word)
    if pattern is None:
        return ()
    lines = text.splitlines()
    values = []
    for match in pattern.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        line_start = text.rfind("\n", 0, match.start()) + 1
        column = match.start() - line_start + 1
        preview = lines[line - 1].strip() if line <= len(lines) else ""
        values.append(FileSearchHit(match.start(), match.end(), line, column, preview[:180]))
    return tuple(values)
