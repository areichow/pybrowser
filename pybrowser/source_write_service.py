from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .model import Document
from .parser import read_document, validate
from .path_locks import PathLockError
from .recovery import OperationKind, RecoveryJournal, RecoveryTransaction, _write_snapshot_to_disk
from .saving import file_signature, stable_read


class SourceWriteError(RuntimeError): pass
class SourceConflictError(SourceWriteError): pass


class SourcePostCommitError(SourceWriteError):
    def __init__(self, message, transaction, document=None, changed_paths=()):
        super().__init__(message)
        self.transaction = transaction
        self.document = document
        self.changed_paths = tuple(changed_paths)


@dataclass(frozen=True, slots=True)
class SaveRequest:
    document: Document
    text: str
    operation: str | OperationKind
    description: str
    location_before: dict | None = None
    location_after: dict | None = None
    origin: object | None = None


@dataclass(frozen=True, slots=True)
class MultiSaveRequest:
    files: tuple[SaveRequest, ...]
    operation: str | OperationKind
    description: str
    location_before: dict | None = None
    location_after: dict | None = None
    origin: object | None = None


@dataclass(frozen=True, slots=True)
class SaveResult:
    document: Document
    transaction: RecoveryTransaction
    changed_paths: tuple[Path, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MultiSaveResult:
    documents: tuple[Document, ...]
    transaction: RecoveryTransaction
    changed_paths: tuple[Path, ...]
    warnings: tuple[str, ...] = ()


class SourceWriteService:
    def __init__(self, journal: RecoveryJournal, notify: Callable | None = None,
                 locks=None, source_store=None):
        self.journal = journal
        self.notify = notify
        self.locks = locks or journal.locks
        self.source_store = source_store

    @staticmethod
    def _replace_bytes(path: Path, data: bytes, mode: int, expected_signature):
        fd, name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            if stable_read(path).signature != expected_signature:
                raise SourceConflictError("The file changed after save preparation. PyBrowser did not replace it.")
            os.replace(temporary, path)
            if os.name != "nt":
                try:
                    descriptor = os.open(path.parent, os.O_RDONLY)
                    try: os.fsync(descriptor)
                    finally: os.close(descriptor)
                except OSError: pass
        finally:
            if temporary.exists(): temporary.unlink()

    @staticmethod
    def _create_bytes_exclusive(path: Path, data: bytes, mode: int):
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.chmod(path, mode)
            if os.name != "nt":
                parent = os.open(path.parent, os.O_RDONLY)
                try: os.fsync(parent)
                finally: os.close(parent)
        except Exception:
            try: path.unlink()
            except OSError: pass
            raise

    def _read_document(self, path):
        return self.source_store.read_document(path) if self.source_store else read_document(path)

    def _post_commit_one(self, path, transaction, origin, candidate, encoding, newline):
        warnings = []
        if self.source_store:
            self.source_store.discard(path)
        try:
            refreshed = self._read_document(path)
        except Exception as exc:
            message = f"Reparse failed after commit: {exc}"
            transaction = self.journal.mark_post_commit_error(transaction, message)
            try: signature = file_signature(path)
            except OSError:
                signature = (0, len(candidate.encode(encoding)), transaction.manifest["files"][0].get("after_sha256", ""))
            refreshed = Document(path, candidate, encoding, newline,
                                 candidate.endswith(("\n", "\r")), signature, ())
            warnings.append(message)
        if self.notify:
            try: self.notify(path, origin)
            except Exception as exc:
                message = f"Workspace notification failed: {exc}"
                transaction = self.journal.mark_post_commit_error(transaction, message)
                warnings.append(message)
        return refreshed, transaction, tuple(warnings)

    def save_documents(self, request: MultiSaveRequest) -> MultiSaveResult:
        files = tuple(request.files)
        if not files:
            raise ValueError("A multi-file save requires at least one candidate")
        paths = tuple(Path(item.document.path).resolve() for item in files)
        if len(set(paths)) != len(paths):
            raise ValueError("A multi-file save cannot contain duplicate paths")
        for item, path in zip(files, paths):
            validate(item.text, str(path))
        prepared = []
        replaced = []
        directory = manifest = after_paths = None
        try:
            with self.locks.acquire_many(paths):
                for item, path in zip(files, paths):
                    try: stable = stable_read(path)
                    except (FileNotFoundError, OSError) as exc:
                        raise SourceConflictError(f"The file could not be read stably: {exc}") from exc
                    if stable.signature != item.document.signature:
                        raise SourceConflictError(f"{path} changed on disk. Reload it before saving.")
                    prepared.append((item, path, stable, item.text.encode(item.document.encoding)))
                specs = ({
                    "path": path, "before": stable.data, "after": after,
                    "encoding": item.document.encoding, "newline": item.document.newline,
                    "mode": stable.mode, "before_exists": True, "after_exists": True,
                } for item, path, stable, after in prepared)
                directory, manifest, after_paths = self.journal.record_writes(
                    specs, operation=str(request.operation), description=request.description,
                    location_before=request.location_before,
                    location_after=request.location_after,
                )
                try:
                    for item, path, stable, after in prepared:
                        self._replace_bytes(path, after, stable.mode, stable.signature)
                        replaced.append((path, stable.data, stable.mode))
                except Exception as exc:
                    rollback_errors = []
                    for path, before, mode in reversed(replaced):
                        try: _write_snapshot_to_disk(path, before, mode)
                        except OSError as rollback: rollback_errors.append(f"{path}: {rollback}")
                    message = str(exc)
                    if rollback_errors:
                        message += "; rollback failed: " + "; ".join(rollback_errors)
                    self.journal.mark_failed(directory, manifest, message)
                    raise
        except PathLockError as exc:
            raise SourceConflictError(str(exc)) from exc
        try:
            transaction, maintenance_warnings = self.journal.finalize_many(
                directory, manifest, after_paths, tuple(item[3] for item in prepared)
            )
        except Exception as exc:
            raise SourcePostCommitError(
                f"The source files were replaced, but core journal finalization failed: {exc}",
                RecoveryTransaction(directory, manifest), changed_paths=paths,
            ) from exc
        documents = []
        warnings = list(maintenance_warnings)
        for item, path, _stable, _after in prepared:
            refreshed, transaction, item_warnings = self._post_commit_one(
                path, transaction, request.origin or item.origin, item.text,
                item.document.encoding, item.document.newline,
            )
            documents.append(refreshed); warnings.extend(item_warnings)
        return MultiSaveResult(tuple(documents), transaction, paths, tuple(warnings))

    def save_document(self, request: SaveRequest) -> SaveResult:
        result = self.save_documents(MultiSaveRequest(
            (request,), request.operation, request.description,
            request.location_before, request.location_after, request.origin,
        ))
        return SaveResult(result.documents[0], result.transaction, result.changed_paths, result.warnings)

    def create_file(self, path: Path, data: bytes, *, operation="create_file",
                    description="Create file", encoding="utf-8", newline="\n",
                    location_before=None, location_after=None, origin=None) -> SaveResult:
        path = Path(path).resolve()
        validate(data.decode(encoding), str(path))
        try:
            with self.locks.acquire(path):
                if path.exists(): raise SourceConflictError(f"{path} already exists")
                directory, manifest, after_snapshot = self.journal.record_write(
                    path, b"", data, operation=str(operation), description=description,
                    encoding=encoding, newline=newline, mode=0o644,
                    location_before=location_before, location_after=location_after,
                )
                manifest["files"][0]["before_exists"] = False
                self.journal.update_prepared(directory, manifest)
                try: self._create_bytes_exclusive(path, data, 0o644)
                except FileExistsError as exc:
                    message = f"{path} was created by another process"
                    self.journal.mark_failed(directory, manifest, message)
                    raise SourceConflictError(message) from exc
                except Exception as exc:
                    self.journal.mark_failed(directory, manifest, str(exc)); raise
        except PathLockError as exc:
            raise SourceConflictError(str(exc)) from exc
        try:
            transaction, maintenance_warnings = self.journal.finalize(
                directory, manifest, after_snapshot, data)
        except Exception as exc:
            raise SourcePostCommitError(
                f"The file was created, but core journal finalization failed: {exc}",
                RecoveryTransaction(directory, manifest)) from exc
        candidate = data.decode(encoding)
        refreshed, transaction, warnings = self._post_commit_one(
            path, transaction, origin, candidate, encoding, newline)
        return SaveResult(refreshed, transaction, (path,), tuple(maintenance_warnings) + warnings)
