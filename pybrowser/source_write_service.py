from __future__ import annotations

import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .parser import read_document, validate
from .recovery import RecoveryJournal
from .saving import changed


class SourceWriteError(RuntimeError):
    pass


class SourceConflictError(SourceWriteError):
    pass


@dataclass(frozen=True, slots=True)
class SaveRequest:
    document: object
    text: str
    operation: str
    description: str
    location_before: dict | None = None
    location_after: dict | None = None
    origin: object | None = None


@dataclass(frozen=True, slots=True)
class SaveResult:
    document: object
    transaction: object
    changed_paths: tuple[Path, ...]


class SourceWriteService:
    """Single authority for validation, conflict checks, journaling, writes and notifications."""

    def __init__(self, journal: RecoveryJournal, notify=None):
        self.journal = journal
        self.notify = notify

    @staticmethod
    def _replace_bytes(path: Path, data: bytes, mode: int):
        fd, name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def save_document(self, request: SaveRequest) -> SaveResult:
        document = request.document
        path = Path(document.path).resolve()
        validate(request.text, str(path))
        if changed(document):
            raise SourceConflictError("The file changed on disk; reload it before saving")
        before = path.read_bytes()
        after = request.text.encode(document.encoding)
        mode = stat.S_IMODE(path.stat().st_mode)
        directory, manifest, after_snapshot = self.journal.record_write(
            path, before, after, operation=request.operation,
            description=request.description, encoding=document.encoding,
            newline=document.newline, mode=mode,
            location_before=request.location_before,
            location_after=request.location_after,
        )
        try:
            self._replace_bytes(path, after, mode)
            transaction = self.journal.finalize(directory, manifest, after_snapshot, after)
            refreshed = read_document(path)
        except BaseException as exc:
            self.journal.mark_failed(directory, manifest, str(exc))
            raise
        if self.notify:
            self.notify(path, request.origin)
        return SaveResult(refreshed, transaction, (path,))

    def create_file(self, path: Path, data: bytes, *, operation="create_file",
                    description="Create file", encoding="utf-8", newline="\n",
                    location_before=None, location_after=None, origin=None) -> SaveResult:
        path = Path(path).resolve()
        if path.exists():
            raise SourceConflictError(f"{path} already exists")
        text = data.decode(encoding)
        validate(text, str(path))
        directory, manifest, after_snapshot = self.journal.record_write(
            path, b"", data, operation=operation, description=description,
            encoding=encoding, newline=newline, mode=0o644,
            location_before=location_before, location_after=location_after,
        )
        manifest["files"][0]["before_exists"] = False
        self.journal.update_prepared(directory, manifest)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._replace_bytes(path, data, 0o644)
            transaction = self.journal.finalize(directory, manifest, after_snapshot, data)
            refreshed = read_document(path)
        except BaseException as exc:
            self.journal.mark_failed(directory, manifest, str(exc))
            raise
        if self.notify:
            self.notify(path, origin)
        return SaveResult(refreshed, transaction, (path,))
