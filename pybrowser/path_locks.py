from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path


class PathLockError(RuntimeError):
    pass


class PathLockService:
    """Cooperative cross-process locks shared by every PyBrowser disk mutation."""

    STALE_SECONDS = 600

    def __init__(self, lock_root: Path):
        self.lock_root = Path(lock_root)

    @staticmethod
    def _pid_exists(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _lock_path(self, path: Path) -> Path:
        resolved = Path(path).resolve()
        digest = hashlib.sha256(
            str(resolved).casefold().encode("utf-8", "surrogatepass")
        ).hexdigest()
        return self.lock_root / f"{digest}.lock"

    @contextmanager
    def acquire(self, path: Path):
        resolved = Path(path).resolve()
        self.lock_root.mkdir(parents=True, exist_ok=True)
        lock = self._lock_path(resolved)
        payload = json.dumps({
            "pid": os.getpid(),
            "created_at": time.time(),
            "path": str(resolved),
        })
        for _attempt in range(2):
            try:
                descriptor = os.open(
                    lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                break
            except FileExistsError:
                try:
                    age = time.time() - lock.stat().st_mtime
                    data = json.loads(lock.read_text(encoding="utf-8"))
                    pid = int(data.get("pid", 0))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    age, pid = 0, 0
                if age > self.STALE_SECONDS and not self._pid_exists(pid):
                    try:
                        lock.unlink()
                    except OSError:
                        pass
                    continue
                raise PathLockError(
                    f"Another PyBrowser disk operation is already in progress for {resolved}"
                )
        else:
            raise PathLockError(f"Could not acquire the PyBrowser path lock for {resolved}")
        try:
            yield resolved
        finally:
            try:
                lock.unlink()
            except OSError:
                pass

    @contextmanager
    def acquire_many(self, paths):
        """Acquire unique locks in canonical order to prevent multi-file deadlocks."""
        unique = {Path(path).resolve() for path in paths}
        ordered = sorted(unique, key=lambda path: str(path).casefold())
        with ExitStack() as stack:
            for path in ordered:
                stack.enter_context(self.acquire(path))
            yield tuple(ordered)
