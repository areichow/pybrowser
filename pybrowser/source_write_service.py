from __future__ import annotations
import os
import hashlib
import json
import time
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from .model import Document
from .parser import read_document, validate
from .recovery import OperationKind, RecoveryJournal, RecoveryTransaction
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
class SaveResult:
    document: Document
    transaction: RecoveryTransaction
    changed_paths: tuple[Path, ...]
    warnings: tuple[str, ...] = ()

class SourceWriteService:
    def __init__(self, journal: RecoveryJournal, notify: Callable | None = None):
        self.journal = journal; self.notify = notify
    @contextmanager
    def _path_lock(self, path: Path):
        locks = self.journal.root / "locks"
        locks.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(str(path.resolve()).casefold().encode("utf-8", "surrogatepass")).hexdigest()
        lock = locks / f"{digest}.lock"
        payload = json.dumps({"pid": os.getpid(), "created_at": time.time(), "path": str(path.resolve())})
        for _attempt in range(2):
            try:
                descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(payload); stream.flush(); os.fsync(stream.fileno())
                break
            except FileExistsError:
                try:
                    age = time.time() - lock.stat().st_mtime
                    data = json.loads(lock.read_text(encoding="utf-8"))
                    pid = int(data.get("pid", 0))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    age, pid = 0, 0
                if age > 600 and not self._pid_exists(pid):
                    try: lock.unlink()
                    except OSError: pass
                    continue
                raise SourceConflictError(f"Another PyBrowser write is already in progress for {path}")
        else:
            raise SourceConflictError(f"Could not acquire the PyBrowser write lock for {path}")
        try:
            yield
        finally:
            try: lock.unlink()
            except OSError: pass

    @staticmethod
    def _pid_exists(pid: int) -> bool:
        if pid <= 0: return False
        try: os.kill(pid, 0)
        except ProcessLookupError: return False
        except PermissionError: return True
        except OSError: return False
        return True

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
                    descriptor=os.open(path.parent, os.O_RDONLY)
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

    def _post_commit(self, path, transaction, origin, candidate, encoding, newline, maintenance_warnings=()):
        warnings = list(maintenance_warnings)
        try:
            refreshed = read_document(path)
        except Exception as exc:
            message = f"Reparse failed after commit: {exc}"
            transaction = self.journal.mark_post_commit_error(transaction, message)
            try:
                signature = file_signature(path)
            except OSError:
                signature = (0, len(candidate.encode(encoding)), transaction.manifest["files"][0].get("after_sha256", ""))
            # The candidate was fully validated before commit. Keep the editor synchronized
            # with committed bytes even when rebuilding structural scopes must be retried.
            refreshed = Document(path, candidate, encoding, newline,
                                 candidate.endswith(("\n", "\r")), signature, ())
            warnings.append(message)
        if self.notify:
            try:
                self.notify(path, origin)
            except Exception as exc:
                message = f"Workspace notification failed: {exc}"
                transaction = self.journal.mark_post_commit_error(transaction, message)
                warnings.append(message)
        return refreshed, transaction, tuple(warnings)

    def save_document(self, request: SaveRequest) -> SaveResult:
        document=request.document; path=Path(document.path).resolve()
        validate(request.text, str(path))
        with self._path_lock(path):
            try:
                stable = stable_read(path)
            except (FileNotFoundError, OSError) as exc:
                raise SourceConflictError(f"The file could not be read stably: {exc}") from exc
            if stable.signature != document.signature:
                raise SourceConflictError("The file changed on disk. Reload it before saving.")
            before=stable.data; after=request.text.encode(document.encoding); mode=stable.mode
            directory, manifest, after_snapshot=self.journal.record_write(path,before,after,operation=str(request.operation),description=request.description,encoding=document.encoding,newline=document.newline,mode=mode,location_before=request.location_before,location_after=request.location_after)
            try: self._replace_bytes(path,after,mode,stable.signature)
            except Exception as exc:
                self.journal.mark_failed(directory,manifest,str(exc)); raise
        try: transaction, maintenance_warnings=self.journal.finalize(directory,manifest,after_snapshot,after)
        except Exception as exc:
            raise SourcePostCommitError(f"The source was replaced, but core journal finalization failed: {exc}", RecoveryTransaction(directory,manifest)) from exc
        refreshed, transaction, warnings = self._post_commit(
            path, transaction, request.origin, request.text, document.encoding,
            document.newline, maintenance_warnings)
        return SaveResult(refreshed, transaction, (path,), warnings)
    def create_file(self,path:Path,data:bytes,*,operation="create_file",description="Create file",encoding="utf-8",newline="\n",location_before=None,location_after=None,origin=None)->SaveResult:
        path=Path(path).resolve()
        validate(data.decode(encoding),str(path))
        with self._path_lock(path):
            if path.exists(): raise SourceConflictError(f"{path} already exists")
            directory,manifest,after_snapshot=self.journal.record_write(path,b"",data,operation=str(operation),description=description,encoding=encoding,newline=newline,mode=0o644,location_before=location_before,location_after=location_after)
            manifest["files"][0]["before_exists"]=False; self.journal.update_prepared(directory,manifest)
            try:
                self._create_bytes_exclusive(path,data,0o644)
            except FileExistsError as exc:
                message = f"{path} was created by another process"
                self.journal.mark_failed(directory,manifest,message)
                raise SourceConflictError(message) from exc
            except Exception as exc:
                self.journal.mark_failed(directory,manifest,str(exc)); raise
        try: transaction, maintenance_warnings=self.journal.finalize(directory,manifest,after_snapshot,data)
        except Exception as exc:
            raise SourcePostCommitError(f"The file was created, but core journal finalization failed: {exc}",RecoveryTransaction(directory,manifest)) from exc
        candidate = data.decode(encoding)
        refreshed, transaction, warnings = self._post_commit(path, transaction, origin, candidate, encoding, newline, maintenance_warnings)
        return SaveResult(refreshed, transaction, (path,), warnings)
