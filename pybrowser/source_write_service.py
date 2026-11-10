from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable

from .model import Document
from .parser import read_document, validate
from .path_locks import PathLockError
from .recovery import OperationKind, RecoveryJournal, RecoveryTransaction, _write_snapshot_to_disk
from .saving import file_signature, stable_read


class WriteMode(StrEnum):
    AUTO_COMMIT = "auto_commit"
    MANUAL_COMMIT = "manual_commit"

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
                 locks=None, source_store=None, write_mode=WriteMode.AUTO_COMMIT):
        self.journal = journal
        self.notify = notify
        self.locks = locks or journal.locks
        self.source_store = source_store
        self.write_mode = WriteMode(write_mode)

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

    def _post_commit_one(self, path, transaction, file_index, origin, candidate, encoding, newline):
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
                signature = (0, len(candidate.encode(encoding)), transaction.manifest["files"][file_index].get("after_sha256", ""))
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

    def _commit_documents(self, request: MultiSaveRequest) -> MultiSaveResult:
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
                    if self.source_store and self.source_store.has_overlay(path):
                        if self.source_store.visible_signature(path) != item.document.signature:
                            raise SourceConflictError(f"{path} changed in the staged World. Reload it before saving.")
                        expected_disk = item.document.disk_signature
                    else:
                        expected_disk = item.document.disk_signature or item.document.signature
                    if stable.signature != expected_disk:
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
        for file_index, (item, path, _stable, _after) in enumerate(prepared):
            refreshed, transaction, item_warnings = self._post_commit_one(
                path, transaction, file_index, request.origin or item.origin, item.text,
                item.document.encoding, item.document.newline,
            )
            documents.append(refreshed); warnings.extend(item_warnings)
        return MultiSaveResult(tuple(documents), transaction, paths, tuple(warnings))

    def _commit_document(self, request: SaveRequest) -> SaveResult:
        result = self._commit_documents(MultiSaveRequest(
            (request,), request.operation, request.description,
            request.location_before, request.location_after, request.origin,
        ))
        return SaveResult(result.documents[0], result.transaction, result.changed_paths, result.warnings)

    def save_documents(self, request: MultiSaveRequest) -> MultiSaveResult:
        if self.write_mode == WriteMode.MANUAL_COMMIT:
            if len(request.files) != 1:
                raise SourceWriteError("Revision 12.21 stages one file per durable transaction.")
            result = self.stage_document(request.files[0])
            return MultiSaveResult((result.document,), result.transaction, result.changed_paths, result.warnings)
        return self._commit_documents(request)

    def save_document(self, request: SaveRequest) -> SaveResult:
        if self.write_mode == WriteMode.MANUAL_COMMIT:
            return self.stage_document(request)
        return self._commit_document(request)

    def stage_document(self, request: SaveRequest) -> SaveResult:
        if self.source_store is None:
            raise SourceWriteError("Manual Commit requires a World source store.")
        path = Path(request.document.path).resolve()
        validate(request.text, str(path))
        after = request.text.encode(request.document.encoding)
        try:
            with self.locks.acquire(path):
                current = self.source_store.overlay(path)
                current_visible = current.signature if current else None
                if current is None:
                    try:
                        disk = stable_read(path)
                    except FileNotFoundError:
                        disk = None
                    store_visible = disk.signature if disk else None
                    current_visible = disk.signature if disk else request.document.signature
                    baseline = request.document.disk_signature if request.document.disk_signature is not None else (disk.signature if disk else None)
                else:
                    store_visible = current.signature
                    baseline = current.disk_signature
                if request.document.signature != current_visible:
                    raise SourceConflictError(f"{path} changed in the staged World. Reload it before saving.")
                if baseline is not None:
                    try:
                        disk_now = stable_read(path)
                    except OSError as exc:
                        raise SourceConflictError(f"The physical baseline could not be read: {exc}") from exc
                    before = disk_now.data if disk_now.signature == baseline else self.journal.snapshot_path(
                        next(tx for active_path, tx, _sig in self.journal.active_overlays() if active_path == path), "before").read_bytes()
                    mode = disk_now.mode
                    before_exists = True
                else:
                    before = b""; mode = 0o644; before_exists = False
                staged_write = self.journal.record_staged_write(
                    path, before, after, disk_signature=baseline,
                    operation=str(request.operation), description=request.description,
                    encoding=request.document.encoding, newline=request.document.newline,
                    mode=mode, before_exists=before_exists,
                    location_before=request.location_before, location_after=request.location_after,
                )
                transaction = staged_write.transaction
                self.source_store.stage_bytes(
                    path, after, encoding=request.document.encoding, mode=mode,
                    disk_signature=baseline, expected_visible_signature=store_visible,
                    transaction_id=transaction.transaction_id, already_locked=True,
                    notify=False,
                )
        except PathLockError as exc:
            raise SourceConflictError(str(exc)) from exc
        document = self.source_store.read_document(path)
        if self.notify: self.notify(path, request.origin)
        return SaveResult(document, transaction, (path,), staged_write.warnings)

    def _commit_staged_paths(self, paths, origin=None):
        if self.source_store is None:
            raise SourceWriteError("No World source store is available.")
        paths = tuple(Path(path).resolve() for path in paths)
        if not paths:
            return ()
        entries = []
        backups = []
        batch = None
        try:
            with self.locks.acquire_many(paths):
                if self.journal.incomplete_staged_commit_batches():
                    raise SourceConflictError(
                        "An interrupted staged commit requires recovery before another commit."
                    )
                for path in paths:
                    overlay = self.source_store.overlay(path)
                    if overlay is None or not overlay.transaction_id:
                        raise SourceConflictError(f"{path} is not staged.")
                    transaction = self.journal.get(overlay.transaction_id)
                    item = transaction.files[0]
                    before_exists = item.get("before_exists", True)
                    if before_exists:
                        try: current = stable_read(path)
                        except OSError as exc:
                            raise SourceConflictError(f"The staged file cannot be read: {exc}") from exc
                        if current.signature != overlay.disk_signature:
                            raise SourceConflictError(f"{path} changed on disk. All staged changes were retained.")
                        backups.append((path, True, current.data, current.mode))
                    else:
                        if path.exists():
                            raise SourceConflictError(f"{path} now exists. All staged changes were retained.")
                        backups.append((path, False, b"", None))
                    entries.append((path, overlay, transaction, before_exists))
                batch = self.journal.prepare_staged_commit_batch(
                    tuple(item[2] for item in entries)
                )
                batch = self.journal.set_staged_batch_status(
                    batch.batch_id, "committing", expected={"prepared"}
                )
                replaced = []
                try:
                    for file_index, (path, overlay, _transaction, before_exists) in enumerate(entries):
                        self.journal.set_staged_file_progress(
                            batch.batch_id, file_index, "replacing", expected="pending"
                        )
                        if before_exists:
                            self._replace_bytes(path, overlay.data, overlay.mode, overlay.disk_signature)
                        else:
                            self._create_bytes_exclusive(path, overlay.data, overlay.mode)
                        replaced.append(path)
                        self.journal.set_staged_file_progress(
                            batch.batch_id, file_index, "replaced", expected="replacing"
                        )
                    completion = self.journal.finalize_staged_commit_batch(batch.batch_id)
                    completed = completion.transactions
                except Exception as exc:
                    rollback_errors = []
                    for path, existed, data, mode in reversed(backups[:len(replaced)]):
                        try:
                            if existed: _write_snapshot_to_disk(path, data, mode)
                            elif path.exists(): path.unlink()
                        except OSError as rollback:
                            rollback_errors.append(f"{path}: {rollback}")
                    if batch is not None:
                        if rollback_errors:
                            self.journal.set_staged_batch_status(
                                batch.batch_id, "rollback_required",
                                expected={"committing"},
                                error=str(exc) + "; rollback failed: " + "; ".join(rollback_errors),
                            )
                        else:
                            for index in range(len(replaced)):
                                self.journal.set_staged_file_progress(
                                    batch.batch_id, index, "rolled_back"
                                )
                            self.journal.set_staged_batch_status(
                                batch.batch_id, "aborted", expected={"committing"}, error=str(exc)
                            )
                    raise
                for path, _overlay, _transaction, _exists in entries:
                    self.source_store.discard(path, notify=False)
        except PathLockError as exc:
            raise SourceConflictError(str(exc)) from exc
        results = []
        for (path, _overlay, _old, _exists), transaction in zip(entries, completed):
            document = self._read_document(path)
            if self.notify: self.notify(path, origin)
            results.append(SaveResult(document, transaction, (path,), completion.warnings))
        return tuple(results)

    def commit_staged(self, path: Path, origin=None) -> SaveResult:
        return self._commit_staged_paths((path,), origin)[0]

    def commit_all_staged(self, origin=None):
        paths = tuple(self.source_store.staged_paths()) if self.source_store else ()
        return self._commit_staged_paths(paths, origin)

    def discard_staged(self, path: Path, origin=None):
        path = Path(path).resolve()
        recovery_paths = {
            item.path for batch in self.journal.incomplete_staged_commit_batches()
            for item in batch.files
        }
        if path in recovery_paths:
            raise SourceConflictError(
                f"{path} belongs to an interrupted staged commit. Resolve the recovery batch first."
            )
        try:
            with self.locks.acquire(path):
                transaction = self.journal.discard_staged(path)
                if self.source_store: self.source_store.discard(path, notify=False)
        except PathLockError as exc:
            raise SourceConflictError(str(exc)) from exc
        if self.notify: self.notify(path, origin)
        return transaction

    def discard_all_staged(self, origin=None):
        return tuple(self.discard_staged(path, origin) for path in tuple(self.source_store.staged_paths()))

    def create_file(self, path: Path, data: bytes, *, operation="create_file",
                    description="Create file", encoding="utf-8", newline="\n",
                    location_before=None, location_after=None, origin=None) -> SaveResult:
        path = Path(path).resolve()
        validate(data.decode(encoding), str(path))
        if self.write_mode == WriteMode.MANUAL_COMMIT:
            if path.exists() or (self.source_store and self.source_store.exists(path)):
                raise SourceConflictError(f"{path} already exists")
            from .parser import build_index
            empty_signature = (-1, 0, __import__("hashlib").sha256(b"").hexdigest())
            empty = Document(path, "", encoding, newline, False, empty_signature, build_index(path, ""), None)
            return self.stage_document(SaveRequest(empty, data.decode(encoding), operation, description,
                                                   location_before, location_after, origin))
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
            path, transaction, 0, origin, candidate, encoding, newline)
        return SaveResult(refreshed, transaction, (path,), tuple(maintenance_warnings) + warnings)
