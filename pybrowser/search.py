from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class SearchMatch:
    start: int
    end: int

def find_all(text: str, query: str, *, case_sensitive: bool = False) -> tuple[SearchMatch, ...]:
    if not query:
        return ()
    haystack = text if case_sensitive else text.casefold()
    needle = query if case_sensitive else query.casefold()
    matches: list[SearchMatch] = []
    position = 0
    while True:
        position = haystack.find(needle, position)
        if position < 0:
            break
        matches.append(SearchMatch(position, position + len(query)))
        position += max(1, len(query))
    return tuple(matches)
