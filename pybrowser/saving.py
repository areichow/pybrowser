from __future__ import annotations
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True, slots=True)
class StableFileRead:
    data: bytes
    signature: tuple[int, int, str]
    mode: int

def stable_read(path: Path, retries=3) -> StableFileRead:
    path = Path(path)
    for _attempt in range(max(1, retries)):
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
        identity_before = (getattr(before, "st_dev", None), getattr(before, "st_ino", None))
        identity_after = (getattr(after, "st_dev", None), getattr(after, "st_ino", None))
        if identity_before == identity_after and before.st_mtime_ns == after.st_mtime_ns and before.st_size == after.st_size == len(data):
            signature = (after.st_mtime_ns, after.st_size, hashlib.sha256(data).hexdigest())
            return StableFileRead(data, signature, stat.S_IMODE(after.st_mode))
    raise OSError(f"{path} changed while it was being read")

def file_signature(path: Path) -> tuple[int, int, str]:
    return stable_read(path).signature

def changed(document, source_store=None) -> bool:
    try:
        if source_store is not None:
            return source_store.visible_signature(document.path) != document.signature
        return file_signature(document.path) != (document.disk_signature or document.signature)
    except (FileNotFoundError, OSError):
        return True
