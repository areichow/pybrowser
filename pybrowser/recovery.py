from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from PySide6.QtCore import QStandardPaths
except ImportError:  # non-UI tests
    QStandardPaths = None

FORMAT_VERSION = 1
INCOMPLETE_STATES = {"prepared", "committing"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def world_id(world_root: Path) -> str:
    value = str(Path(world_root).resolve()).casefold().encode("utf-8", "surrogatepass")
    return hashlib.sha256(value).hexdigest()[:20]


def default_history_root() -> Path:
    if QStandardPaths is not None:
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        if base:
            return Path(base) / "history"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "PyBrowser/history"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "pybrowser/history"


def _json_write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".manifest.", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists(): temp.unlink()


def _safe_relative(path: Path, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return Path("external") / hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12] / path.name


@dataclass(frozen=True, slots=True)
class RecoveryTransaction:
    directory: Path
    manifest: dict

    @property
    def transaction_id(self): return self.manifest["transaction_id"]
    @property
    def status(self): return self.manifest.get("status", "unknown")
    @property
    def description(self): return self.manifest.get("description", self.manifest.get("operation", "Change"))
    @property
    def timestamp(self): return self.manifest.get("timestamp", "")
    @property
    def pinned(self): return bool(self.manifest.get("pinned", False))


class RecoveryJournal:
    def __init__(self, world_root: Path, history_root: Path | None = None, max_transactions=200, min_days=30, max_megabytes=500):
        self.world_root = Path(world_root).resolve()
        self.root = (history_root or default_history_root()) / world_id(self.world_root)
        self.max_transactions = max(1, int(max_transactions))
        self.min_days = max(0, int(min_days))
        self.max_bytes = max(1, int(max_megabytes)) * 1024 * 1024
        self.root.mkdir(parents=True, exist_ok=True)
        metadata = self.root / "world.json"
        if not metadata.exists():
            _json_write(metadata, {"format": FORMAT_VERSION, "world_root": str(self.world_root)})

    def transactions(self) -> tuple[RecoveryTransaction, ...]:
        values = []
        for directory in self.root.iterdir():
            manifest_path = directory / "manifest.json"
            if not directory.is_dir() or not manifest_path.exists(): continue
            try: manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError): continue
            values.append(RecoveryTransaction(directory, manifest))
        return tuple(sorted(values, key=lambda item: item.timestamp, reverse=True))

    def incomplete(self):
        return tuple(item for item in self.transactions() if item.status in INCOMPLETE_STATES)

    def record_write(self, path: Path, before: bytes, after: bytes, *, operation="save_file", description="Save file", encoding="utf-8", newline="\n", location_before=None, location_after=None, mode=None, writer=None):
        path = Path(path).resolve()
        now = datetime.now(timezone.utc)
        txid = now.strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
        directory = self.root / txid
        relative = _safe_relative(path, self.world_root)
        before_path = directory / "before" / relative
        after_path = directory / "after" / relative
        before_path.parent.mkdir(parents=True, exist_ok=True)
        after_path.parent.mkdir(parents=True, exist_ok=True)
        before_path.write_bytes(before)
        manifest = {
            "format": FORMAT_VERSION,
            "transaction_id": txid,
            "timestamp": now.isoformat(),
            "description": description,
            "operation": operation,
            "status": "prepared",
            "pinned": False,
            "world_root": str(self.world_root),
            "writer": writer or "PyBrowser",
            "files": [{
                "path": str(path), "relative_path": relative.as_posix(),
                "encoding": encoding, "newline": "CRLF" if newline == "\r\n" else "LF",
                "mode": mode, "before_sha256": sha256_bytes(before),
                "after_sha256": sha256_bytes(after),
                "before_snapshot": str(Path("before") / relative),
                "after_snapshot": str(Path("after") / relative),
            }],
            "location_before": location_before,
            "location_after": location_after,
        }
        _json_write(directory / "manifest.json", manifest)
        manifest["status"] = "committing"
        _json_write(directory / "manifest.json", manifest)
        return directory, manifest, after_path

    def finalize(self, directory: Path, manifest: dict, after_path: Path, after: bytes):
        after_path.write_bytes(after)
        manifest["status"] = "committed"
        manifest["committed_at"] = datetime.now(timezone.utc).isoformat()
        _json_write(directory / "manifest.json", manifest)
        self.prune()
        return RecoveryTransaction(directory, manifest)

    def mark_failed(self, directory: Path, manifest: dict, message: str):
        manifest["status"] = "failed"
        manifest["error"] = message
        _json_write(directory / "manifest.json", manifest)

    def set_pinned(self, transaction: RecoveryTransaction, pinned: bool):
        manifest = dict(transaction.manifest); manifest["pinned"] = bool(pinned)
        _json_write(transaction.directory / "manifest.json", manifest)

    def snapshot_path(self, transaction: RecoveryTransaction, side: str, file_index=0):
        key = "before_snapshot" if side == "before" else "after_snapshot"
        return transaction.directory / transaction.manifest["files"][file_index][key]

    def restore_as(self, transaction: RecoveryTransaction, side: str, destination: Path, file_index=0):
        source = self.snapshot_path(transaction, side, file_index)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def inspect_state(self, transaction: RecoveryTransaction):
        states = []
        for item in transaction.manifest.get("files", []):
            path = Path(item["path"])
            current = sha256_bytes(path.read_bytes()) if path.exists() else None
            if current == item.get("before_sha256"): state = "current equals before"
            elif current == item.get("after_sha256"): state = "current equals after"
            else: state = "current differs from both"
            states.append((path, state))
        return tuple(states)

    def prune(self):
        completed = [item for item in self.transactions() if item.status == "committed" and not item.pinned]
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.min_days)
        total = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
        for index, item in enumerate(reversed(completed)):
            try: timestamp = datetime.fromisoformat(item.timestamp)
            except ValueError: timestamp = datetime.min.replace(tzinfo=timezone.utc)
            over_count = len(completed) - index > self.max_transactions
            over_size = total > self.max_bytes
            if not (over_count or over_size) or timestamp > cutoff: continue
            size = sum(p.stat().st_size for p in item.directory.rglob("*") if p.is_file())
            shutil.rmtree(item.directory, ignore_errors=True); total -= size


def journaled_atomic_write(document, text: str, journal: RecoveryJournal, *, operation="save_file", description="Save file", location_before=None, location_after=None):
    path = document.path.resolve()
    before = path.read_bytes()
    after = text.encode(document.encoding)
    mode = stat.S_IMODE(path.stat().st_mode)
    directory, manifest, after_snapshot = journal.record_write(
        path, before, after, operation=operation, description=description,
        encoding=document.encoding, newline=document.newline, mode=mode,
        location_before=location_before, location_after=location_after,
    )
    from .saving import atomic_write
    try:
        atomic_write(document, text)
        return journal.finalize(directory, manifest, after_snapshot, after)
    except BaseException as exc:
        journal.mark_failed(directory, manifest, str(exc))
        raise


def journaled_create_file(path: Path, data: bytes, journal: RecoveryJournal, *, operation="create_file", description="Create file", encoding="utf-8", newline="\n"):
    path = Path(path).resolve()
    if path.exists(): raise FileExistsError(path)
    directory, manifest, after_snapshot = journal.record_write(path, b"", data, operation=operation, description=description, encoding=encoding, newline=newline, mode=0o644)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
        temp = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if temp.exists(): temp.unlink()
        return journal.finalize(directory, manifest, after_snapshot, data)
    except BaseException as exc:
        journal.mark_failed(directory, manifest, str(exc)); raise
