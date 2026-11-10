"""Process-safe module indexing entry point with no Qt object dependencies."""
from pathlib import Path

from .parser import ParseError, document_from_stable, read_document
from .saving import StableFileRead
import hashlib
from .semantic import analyze_source


def index_module(path_value: str, source_bytes=None):
    path = Path(path_value)
    try:
        if source_bytes is None:
            document = read_document(path)
        else:
            signature = (-1, len(source_bytes), hashlib.sha256(source_bytes).hexdigest())
            document = document_from_stable(path, StableFileRead(source_bytes, signature, 0o644))
        semantic = analyze_source(path, document.text)
        return path, document.scopes, semantic, None
    except (OSError, UnicodeError, ParseError, SyntaxError, ValueError) as exc:
        return path, None, None, str(exc)
