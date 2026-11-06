from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from PySide6.QtCore import QStandardPaths
except ImportError:
    QStandardPaths = None

FORMAT_VERSION = 2
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
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _safe_relative(path: Path, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]
        return Path("external") / digest / path.name


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
    @property
    def damaged(self): return bool(self.manifest.get("damaged", False))


class RecoveryJournal:
    """SQLite-indexed metadata with portable per-transaction JSON manifests."""

    def __init__(self, world_root: Path, history_root: Path | None = None,
                 max_transactions=200, min_days=30, max_megabytes=500):
        self.world_root = Path(world_root).resolve()
        self.root = (history_root or default_history_root()) / world_id(self.world_root)
        self.max_transactions = max(1, int(max_transactions))
        self.min_days = max(0, int(min_days))
        self.max_bytes = max(1, int(max_megabytes)) * 1024 * 1024
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / "journal.sqlite3"
        metadata = self.root / "world.json"
        if not metadata.exists():
            _json_write(metadata, {"format": FORMAT_VERSION, "world_root": str(self.world_root)})
        self._initialize_database()
        self.reconcile()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize_database(self):
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = FULL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY,
                    timestamp_utc TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    committed_to_disk INTEGER NOT NULL DEFAULT 1,
                    world_root TEXT NOT NULL,
                    writer TEXT,
                    location_before_json TEXT,
                    location_after_json TEXT,
                    committed_at TEXT,
                    error TEXT,
                    damaged INTEGER NOT NULL DEFAULT 0,
                    transaction_directory TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transaction_files (
                    transaction_id TEXT NOT NULL,
                    file_index INTEGER NOT NULL,
                    absolute_path TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    encoding TEXT,
                    newline TEXT,
                    mode INTEGER,
                    before_sha256 TEXT,
                    after_sha256 TEXT,
                    before_snapshot TEXT,
                    after_snapshot TEXT,
                    PRIMARY KEY (transaction_id, file_index),
                    FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_transactions_timestamp
                    ON transactions(timestamp_utc DESC);
                CREATE INDEX IF NOT EXISTS idx_transactions_status
                    ON transactions(status);
                CREATE INDEX IF NOT EXISTS idx_transactions_disk
                    ON transactions(committed_to_disk, timestamp_utc);
                CREATE INDEX IF NOT EXISTS idx_transaction_files_path
                    ON transaction_files(absolute_path);
            """)

    @staticmethod
    def _manifest_json(value):
        return json.dumps(value, sort_keys=True) if value is not None else None

    def _upsert_manifest(self, directory: Path, manifest: dict, db=None):
        owns_connection = db is None
        connection = db or self._connect()
        try:
            connection.execute("""
                INSERT INTO transactions (
                    id, timestamp_utc, operation, description, status, pinned,
                    committed_to_disk, world_root, writer,
                    location_before_json, location_after_json, committed_at,
                    error, damaged, transaction_directory
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timestamp_utc=excluded.timestamp_utc,
                    operation=excluded.operation,
                    description=excluded.description,
                    status=excluded.status,
                    pinned=excluded.pinned,
                    committed_to_disk=excluded.committed_to_disk,
                    world_root=excluded.world_root,
                    writer=excluded.writer,
                    location_before_json=excluded.location_before_json,
                    location_after_json=excluded.location_after_json,
                    committed_at=excluded.committed_at,
                    error=excluded.error,
                    damaged=excluded.damaged,
                    transaction_directory=excluded.transaction_directory
            """, (
                manifest["transaction_id"], manifest.get("timestamp", ""),
                manifest.get("operation", "unknown"), manifest.get("description", "Change"),
                manifest.get("status", "unknown"), int(bool(manifest.get("pinned", False))),
                int(bool(manifest.get("committed_to_disk", True))),
                manifest.get("world_root", str(self.world_root)), manifest.get("writer"),
                self._manifest_json(manifest.get("location_before")),
                self._manifest_json(manifest.get("location_after")),
                manifest.get("committed_at"), manifest.get("error"),
                int(bool(manifest.get("damaged", False))), str(directory),
            ))
            connection.execute("DELETE FROM transaction_files WHERE transaction_id = ?", (manifest["transaction_id"],))
            for index, item in enumerate(manifest.get("files", [])):
                connection.execute("""
                    INSERT INTO transaction_files (
                        transaction_id, file_index, absolute_path, relative_path,
                        encoding, newline, mode, before_sha256, after_sha256,
                        before_snapshot, after_snapshot
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    manifest["transaction_id"], index, item.get("path", ""),
                    item.get("relative_path", ""), item.get("encoding"),
                    item.get("newline"), item.get("mode"), item.get("before_sha256"),
                    item.get("after_sha256"), item.get("before_snapshot"),
                    item.get("after_snapshot"),
                ))
            if owns_connection:
                connection.commit()
        finally:
            if owns_connection:
                connection.close()

    def _manifest_from_row(self, row, files):
        def parse_json(value):
            if not value:
                return None
            try: return json.loads(value)
            except ValueError: return None
        return {
            "format": FORMAT_VERSION,
            "transaction_id": row["id"], "timestamp": row["timestamp_utc"],
            "operation": row["operation"], "description": row["description"],
            "status": row["status"], "pinned": bool(row["pinned"]),
            "committed_to_disk": bool(row["committed_to_disk"]),
            "world_root": row["world_root"], "writer": row["writer"],
            "location_before": parse_json(row["location_before_json"]),
            "location_after": parse_json(row["location_after_json"]),
            "committed_at": row["committed_at"], "error": row["error"],
            "damaged": bool(row["damaged"]), "files": [
                {**dict(item), "path": item["absolute_path"]} for item in files
            ],
        }

    def reconcile(self):
        """Import legacy manifests and flag missing snapshot files."""
        manifest_entries = {}
        for directory in self.root.iterdir():
            manifest_path = directory / "manifest.json"
            if not directory.is_dir() or not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            manifest_entries[manifest.get("transaction_id", directory.name)] = (directory, manifest)

        with self._connect() as db:
            for directory, manifest in manifest_entries.values():
                manifest.setdefault("format", FORMAT_VERSION)
                manifest.setdefault("committed_to_disk", True)
                damaged = False
                for item in manifest.get("files", []):
                    for key in ("before_snapshot", "after_snapshot"):
                        relative = item.get(key)
                        if relative and not (directory / relative).exists():
                            damaged = True
                manifest["damaged"] = damaged
                self._upsert_manifest(directory, manifest, db)
                if damaged:
                    _json_write(directory / "manifest.json", manifest)

            rows = db.execute("SELECT id, transaction_directory FROM transactions").fetchall()
            for row in rows:
                directory = Path(row["transaction_directory"])
                if row["id"] not in manifest_entries and not (directory / "manifest.json").exists():
                    db.execute("UPDATE transactions SET damaged = 1 WHERE id = ?", (row["id"],))

    def transactions(self) -> tuple[RecoveryTransaction, ...]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM transactions ORDER BY timestamp_utc DESC").fetchall()
            values = []
            for row in rows:
                files = db.execute("SELECT * FROM transaction_files WHERE transaction_id = ? ORDER BY file_index", (row["id"],)).fetchall()
                directory = Path(row["transaction_directory"])
                values.append(RecoveryTransaction(directory, self._manifest_from_row(row, files)))
        return tuple(values)

    def incomplete(self):
        with self._connect() as db:
            marks = ",".join("?" for _ in INCOMPLETE_STATES)
            rows = db.execute(f"SELECT * FROM transactions WHERE status IN ({marks}) ORDER BY timestamp_utc DESC", tuple(sorted(INCOMPLETE_STATES))).fetchall()
            values = []
            for row in rows:
                files = db.execute("SELECT * FROM transaction_files WHERE transaction_id = ? ORDER BY file_index", (row["id"],)).fetchall()
                values.append(RecoveryTransaction(Path(row["transaction_directory"]), self._manifest_from_row(row, files)))
        return tuple(values)

    def record_write(self, path: Path, before: bytes, after: bytes, *, operation="save_file",
                     description="Save file", encoding="utf-8", newline="\n",
                     location_before=None, location_after=None, mode=None, writer=None):
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
            "format": FORMAT_VERSION, "transaction_id": txid,
            "timestamp": now.isoformat(), "description": description,
            "operation": operation, "status": "prepared", "pinned": False,
            "committed_to_disk": True, "world_root": str(self.world_root),
            "writer": writer or "PyBrowser", "damaged": False,
            "files": [{
                "path": str(path), "relative_path": relative.as_posix(),
                "encoding": encoding, "newline": "CRLF" if newline == "\r\n" else "LF",
                "mode": mode, "before_sha256": sha256_bytes(before),
                "after_sha256": sha256_bytes(after),
                "before_snapshot": str(Path("before") / relative),
                "after_snapshot": str(Path("after") / relative),
            }],
            "location_before": location_before, "location_after": location_after,
        }
        _json_write(directory / "manifest.json", manifest)
        self._upsert_manifest(directory, manifest)
        manifest["status"] = "committing"
        _json_write(directory / "manifest.json", manifest)
        self._upsert_manifest(directory, manifest)
        return directory, manifest, after_path

    def finalize(self, directory: Path, manifest: dict, after_path: Path, after: bytes):
        after_path.write_bytes(after)
        manifest["status"] = "committed"
        manifest["committed_at"] = datetime.now(timezone.utc).isoformat()
        _json_write(directory / "manifest.json", manifest)
        self._upsert_manifest(directory, manifest)
        self.prune()
        return RecoveryTransaction(directory, manifest)

    def mark_failed(self, directory: Path, manifest: dict, message: str):
        manifest["status"] = "failed"
        manifest["error"] = message
        _json_write(directory / "manifest.json", manifest)
        self._upsert_manifest(directory, manifest)

    def set_pinned(self, transaction: RecoveryTransaction, pinned: bool):
        manifest = dict(transaction.manifest)
        manifest["pinned"] = bool(pinned)
        _json_write(transaction.directory / "manifest.json", manifest)
        self._upsert_manifest(transaction.directory, manifest)

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
            path = Path(item["absolute_path"] if "absolute_path" in item else item["path"])
            current = sha256_bytes(path.read_bytes()) if path.exists() else None
            if current == item.get("before_sha256"): state = "current equals before"
            elif current == item.get("after_sha256"): state = "current equals after"
            else: state = "current differs from both"
            states.append((path, state))
        return tuple(states)

    def database_settings(self):
        with self._connect() as db:
            return {
                "journal_mode": db.execute("PRAGMA journal_mode").fetchone()[0],
                "synchronous": db.execute("PRAGMA synchronous").fetchone()[0],
                "foreign_keys": db.execute("PRAGMA foreign_keys").fetchone()[0],
                "busy_timeout": db.execute("PRAGMA busy_timeout").fetchone()[0],
            }

    def prune(self):
        completed = [item for item in self.transactions() if item.status == "committed" and not item.pinned]
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.min_days)
        total = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
        removed = []
        for index, item in enumerate(reversed(completed)):
            try: timestamp = datetime.fromisoformat(item.timestamp)
            except ValueError: timestamp = datetime.min.replace(tzinfo=timezone.utc)
            over_count = len(completed) - index > self.max_transactions
            over_size = total > self.max_bytes
            if not (over_count or over_size) or timestamp > cutoff:
                continue
            size = sum(p.stat().st_size for p in item.directory.rglob("*") if p.is_file())
            removed.append(item.transaction_id)
            shutil.rmtree(item.directory, ignore_errors=True)
            total -= size
        if removed:
            with self._connect() as db:
                db.executemany("DELETE FROM transactions WHERE id = ?", ((item,) for item in removed))


def journaled_atomic_write(document, text: str, journal: RecoveryJournal, *, operation="save_file",
                             description="Save file", location_before=None, location_after=None):
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


def journaled_create_file(path: Path, data: bytes, journal: RecoveryJournal, *, operation="create_file",
                           description="Create file", encoding="utf-8", newline="\n"):
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError(path)
    directory, manifest, after_snapshot = journal.record_write(
        path, b"", data, operation=operation, description=description,
        encoding=encoding, newline=newline, mode=0o644,
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
        temp = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()
        return journal.finalize(directory, manifest, after_snapshot, data)
    except BaseException as exc:
        journal.mark_failed(directory, manifest, str(exc))
        raise
