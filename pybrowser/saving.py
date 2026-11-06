from __future__ import annotations

import hashlib
from pathlib import Path


def file_signature(path: Path) -> tuple[int, int, str]:
    data = path.read_bytes()
    details = path.stat()
    return details.st_mtime_ns, details.st_size, hashlib.sha256(data).hexdigest()


def changed(document) -> bool:
    try:
        return file_signature(document.path) != document.signature
    except FileNotFoundError:
        return True
