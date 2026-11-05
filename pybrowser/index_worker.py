"""Process-safe module indexing entry point with no Qt object dependencies."""
from pathlib import Path

from .parser import ParseError, read_document
from .semantic import analyze_source


def index_module(path_value: str):
    path = Path(path_value)
    try:
        document = read_document(path)
        semantic = analyze_source(path, document.text)
        return path, document.scopes, semantic, None
    except (OSError, UnicodeError, ParseError, SyntaxError, ValueError) as exc:
        return path, None, None, str(exc)
