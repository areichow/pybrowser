from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

class Kind(StrEnum):
    IMPORTS="imports"; ASSIGNMENT="assignment"; FUNCTION="function"; METHOD="method"; MAIN="main guard"; BLOCK="block"; STATEMENT="statement"

@dataclass(frozen=True, slots=True)
class Span:
    start:int; end:int; first:int; last:int

@dataclass(frozen=True, slots=True)
class Member:
    scope:str; category:str; label:str; kind:Kind; span:Span

@dataclass(frozen=True, slots=True)
class Scope:
    name:str; members:tuple[Member,...]

@dataclass(slots=True)
class Document:
    path:Path; text:str; encoding:str; newline:str; final_newline:bool; signature:tuple[int,int,str]; scopes:tuple[Scope,...]
    def source(self, member:Member)->str: return self.text[member.span.start:member.span.end]
