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
                    undone_at TEXT,
                    redone_at TEXT,
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
                    before_exists INTEGER NOT NULL DEFAULT 1,
                    after_exists INTEGER NOT NULL DEFAULT 1,
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
            columns = {row[1] for row in db.execute("PRAGMA table_info(transactions)")}
            if "undone_at" not in columns:
                db.execute("ALTER TABLE transactions ADD COLUMN undone_at TEXT")
            if "redone_at" not in columns:
                db.execute("ALTER TABLE transactions ADD COLUMN redone_at TEXT")
            file_columns = {row[1] for row in db.execute("PRAGMA table_info(transaction_files)")}
            if "before_exists" not in file_columns:
                db.execute("ALTER TABLE transaction_files ADD COLUMN before_exists INTEGER NOT NULL DEFAULT 1")
            if "after_exists" not in file_columns:
                db.execute("ALTER TABLE transaction_files ADD COLUMN after_exists INTEGER NOT NULL DEFAULT 1")

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
                    undone_at, redone_at, error, damaged, transaction_directory
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    undone_at=excluded.undone_at,
                    redone_at=excluded.redone_at,
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
                manifest.get("committed_at"), manifest.get("undone_at"),
                manifest.get("redone_at"), manifest.get("error"),
                int(bool(manifest.get("damaged", False))), str(directory),
            ))
            connection.execute("DELETE FROM transaction_files WHERE transaction_id = ?", (manifest["transaction_id"],))
            for index, item in enumerate(manifest.get("files", [])):
                connection.execute("""
                    INSERT INTO transaction_files (
                        transaction_id, file_index, absolute_path, relative_path,
                        encoding, newline, mode, before_exists, after_exists,
                        before_sha256, after_sha256, before_snapshot, after_snapshot
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    manifest["transaction_id"], index, item.get("path", ""),
                    item.get("relative_path", ""), item.get("encoding"),
                    item.get("newline"), item.get("mode"),
                    int(bool(item.get("before_exists", True))), int(bool(item.get("after_exists", True))),
                    item.get("before_sha256"), item.get("after_sha256"), item.get("before_snapshot"),
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
            "committed_at": row["committed_at"], "undone_at": row["undone_at"],
            "redone_at": row["redone_at"], "error": row["error"],
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
                "mode": mode, "before_exists": path.exists(), "after_exists": True,
                "before_sha256": sha256_bytes(before),
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

    def update_prepared(self, directory: Path, manifest: dict):
        """Persist metadata changes made after preparation but before disk commit."""
        _json_write(directory / "manifest.json", manifest)
        self._upsert_manifest(directory, manifest)

    def finalize(self, directory: Path, manifest: dict, after_path: Path, after: bytes):
        after_path.write_bytes(after)
        manifest["status"] = "committed"
        manifest["committed_at"] = datetime.now(timezone.utc).isoformat()
        _json_write(directory / "manifest.json", manifest)
        self._upsert_manifest(directory, manifest)
        self.prune()
        callback = getattr(self, "on_change", None)
        if callback:
            callback()
        return RecoveryTransaction(directory, manifest)

    def mark_failed(self, directory: Path, manifest: dict, message: str):
        manifest["status"] = "failed"
        manifest["error"] = message
        _json_write(directory / "manifest.json", manifest)
        self._upsert_manifest(directory, manifest)
        callback = getattr(self, "on_change", None)
        if callback:
            callback()

    def set_pinned(self, transaction: RecoveryTransaction, pinned: bool):
        manifest = dict(transaction.manifest)
        manifest["pinned"] = bool(pinned)
        _json_write(transaction.directory / "manifest.json", manifest)
        self._upsert_manifest(transaction.directory, manifest)
        callback = getattr(self, "on_change", None)
        if callback:
            callback()

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
            before_exists = item.get("before_exists", transaction.manifest.get("operation") != "create_package_init")
            after_exists = item.get("after_exists", True)
            before_expected = item.get("before_sha256") if before_exists else None
            after_expected = item.get("after_sha256") if after_exists else None
            if current == before_expected: state = "current equals before"
            elif current == after_expected: state = "current equals after"
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


class RecoveryConflictError(RuntimeError):
    def __init__(self, message, transaction=None, states=()):
        super().__init__(message)
        self.transaction = transaction
        self.states = tuple(states)


def _transaction_path(item):
    return Path(item.get("absolute_path") or item.get("path", "")).resolve()


def _write_snapshot_to_disk(path: Path, data: bytes, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".undo.tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, int(mode))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _recovery_set_status(self, transaction, status, **extra):
    manifest = dict(transaction.manifest)
    manifest["status"] = status
    manifest.update(extra)
    _json_write(transaction.directory / "manifest.json", manifest)
    self._upsert_manifest(transaction.directory, manifest)
    callback = getattr(self, "on_change", None)
    if callback:
        callback()
    return RecoveryTransaction(transaction.directory, manifest)


def _recovery_get(self, transaction_id):
    return next((item for item in self.transactions() if item.transaction_id == transaction_id), None)


def _recovery_latest_undo(self):
    return next((item for item in self.transactions()
                 if item.status in {"committed", "redone"} and not item.damaged), None)


def _recovery_latest_redo(self):
    return next((item for item in self.transactions()
                 if item.status == "undone" and not item.damaged), None)


def _recovery_apply(self, transaction, direction):
    if direction not in {"undo", "redo"}:
        raise ValueError(direction)
    expected_statuses = {"committed", "redone"} if direction == "undo" else {"undone"}
    if transaction.status not in expected_statuses:
        raise RecoveryConflictError(
            f"Transaction {transaction.transaction_id} is {transaction.status}, so it cannot be {direction}ne.",
            transaction,
        )
    if transaction.damaged:
        raise RecoveryConflictError("The transaction is damaged and cannot be applied automatically.", transaction)
    source_side = "before" if direction == "undo" else "after"
    expected_hash_key = "after_sha256" if direction == "undo" else "before_sha256"
    states = self.inspect_state(transaction)
    conflicts = []
    for index, (path, state) in enumerate(states):
        item = transaction.manifest["files"][index]
        current = sha256_bytes(path.read_bytes()) if path.exists() else None
        expected_exists_key = "after_exists" if direction == "undo" else "before_exists"
        expected_exists = item.get(expected_exists_key)
        if expected_exists is None:
            expected_exists = not (direction == "redo" and transaction.manifest.get("operation") == "create_package_init")
        expected = item.get(expected_hash_key) if expected_exists else None
        if current != expected:
            conflicts.append((path, state))
    if conflicts:
        raise RecoveryConflictError(
            f"Cannot {direction} because {len(conflicts)} affected file(s) no longer match the expected hash.",
            transaction, conflicts,
        )

    backups = []
    changed_paths = []
    try:
        for index, item in enumerate(transaction.manifest.get("files", [])):
            path = _transaction_path(item)
            existed = path.exists()
            current = path.read_bytes() if existed else b""
            backups.append((path, existed, current, stat.S_IMODE(path.stat().st_mode) if existed else None))
            snapshot = self.snapshot_path(transaction, source_side, index)
            data = snapshot.read_bytes()
            before_exists = item.get("before_exists")
            after_exists = item.get("after_exists")
            if before_exists is None:
                before_exists = transaction.manifest.get("operation") != "create_package_init"
            if after_exists is None:
                after_exists = True
            target_exists = before_exists if direction == "undo" else after_exists
            if not target_exists:
                if path.exists():
                    path.unlink()
            else:
                _write_snapshot_to_disk(path, data, item.get("mode"))
            changed_paths.append(path)
    except BaseException:
        for path, existed, data, mode in reversed(backups):
            try:
                if existed:
                    _write_snapshot_to_disk(path, data, mode)
                elif path.exists():
                    path.unlink()
            except OSError:
                pass
        raise

    timestamp = datetime.now(timezone.utc).isoformat()
    if direction == "undo":
        result = self.set_status(transaction, "undone", undone_at=timestamp)
    else:
        result = self.set_status(transaction, "redone", redone_at=timestamp)
    return result, tuple(changed_paths)


RecoveryJournal.set_status = _recovery_set_status
RecoveryJournal.get = _recovery_get
RecoveryJournal.latest_undo = _recovery_latest_undo
RecoveryJournal.latest_redo = _recovery_latest_redo
RecoveryJournal.apply_transaction = _recovery_apply
