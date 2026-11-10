from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

class Kind(StrEnum):
    CATEGORY = "category"
    DOCUMENTATION = "documentation"
    IMPORTS = "imports"
    TYPE_ALIAS = "type alias"
    ASSIGNMENT = "assignment"
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    MAIN = "main guard"
    IF = "if block"
    FOR = "for block"
    WHILE = "while block"
    WITH = "with block"
    TRY = "try block"
    MATCH = "match block"
    STATEMENT = "statement"

@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int
    first: int
    last: int

@dataclass(frozen=True, slots=True)
class Member:
    scope: str
    category: str
    label: str
    kind: Kind
    span: Span
    synthetic: bool = False
    tooltip: str = ""

@dataclass(frozen=True, slots=True)
class Scope:
    name: str
    members: tuple[Member, ...]
    parent: str | None = None

@dataclass(slots=True)
class Document:
    path: Path
    text: str
    encoding: str
    newline: str
    final_newline: bool
    signature: tuple[int, int, str]
    scopes: tuple[Scope, ...]
    disk_signature: tuple[int, int, str] | None = None

    def source(self, member: Member) -> str:
        return self.text[member.span.start:member.span.end]
