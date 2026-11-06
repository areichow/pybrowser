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
from enum import StrEnum
from typing import TypedDict
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from PySide6.QtCore import QStandardPaths
except ImportError:
    QStandardPaths = None

FORMAT_VERSION = 3
SCHEMA_VERSION = 5

class RecoverySchemaError(RuntimeError):
    pass

class TransactionStatus(StrEnum):
    PREPARED = "prepared"
    COMMITTING = "committing"
    COMMITTED = "committed"
    UNDONE = "undone"
    REDONE = "redone"
    SUPERSEDED = "superseded"
    ABORTED = "aborted"
    REVIEWED = "reviewed"
    FAILED = "failed"
    UNDOING = "undoing"
    REDOING = "redoing"
    PRUNING = "pruning"

class OperationKind(StrEnum):
    SAVE_MEMBER = "save_member"
    SAVE_FILE = "save_file"
    MOVE_MEMBER = "move_member"
    DUPLICATE_MEMBER = "duplicate_member"
    DELETE_MEMBER = "delete_member"
    RENAME_CATEGORY = "rename_category"
    CONVERT_METHOD_KIND = "convert_method_kind"
    CREATE_PACKAGE_INIT = "create_package_init"
    ADD_FUNCTION = "add_function"
    ADD_CLASS = "add_class"
    ADD_METHOD = "add_method"
    STRUCTURAL_EDIT = "structural_edit"

class TransactionFileManifest(TypedDict, total=False):
    path: str
    relative_path: str
    encoding: str
    newline: str
    mode: int | None
    before_exists: bool
    after_exists: bool
    before_sha256: str
    after_sha256: str
    before_snapshot: str
    after_snapshot: str

class TransactionManifest(TypedDict, total=False):
    format: int
    transaction_id: str
    timestamp: str
    operation: str
    description: str
    status: str
    pinned: bool
    committed_to_disk: bool
    world_root: str
    writer: str
    files: list[TransactionFileManifest]
    location_before: dict | None
    location_after: dict | None
    committed_at: str
    undone_at: str
    redone_at: str
    recovered_at: str
    reviewed_at: str
    superseded_at: str
    error: str
    post_commit_error: str
    post_commit_error_at: str
    damaged: bool

WRITE_INCOMPLETE_STATES = {TransactionStatus.PREPARED.value, TransactionStatus.COMMITTING.value}
HISTORY_INCOMPLETE_STATES = {TransactionStatus.UNDOING.value, TransactionStatus.REDOING.value}
INCOMPLETE_STATES = WRITE_INCOMPLETE_STATES | HISTORY_INCOMPLETE_STATES
TERMINAL_STATES = {
    TransactionStatus.COMMITTED.value, TransactionStatus.UNDONE.value,
    TransactionStatus.REDONE.value, TransactionStatus.SUPERSEDED.value,
    TransactionStatus.ABORTED.value, TransactionStatus.REVIEWED.value,
    TransactionStatus.FAILED.value,
}


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


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    except OSError:
        pass

def _write_durable_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    _fsync_directory(path.parent)

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
        _fsync_directory(path.parent)
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
    manifest: TransactionManifest

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
    @property
    def operation(self): return self.manifest.get("operation", "unknown")
    @property
    def files(self): return tuple(self.manifest.get("files", ()))
    @property
    def committed_at(self): return self.manifest.get("committed_at")
    @property
    def undone_at(self): return self.manifest.get("undone_at")
    @property
    def redone_at(self): return self.manifest.get("redone_at")
    @property
    def recovered_at(self): return self.manifest.get("recovered_at")
    @property
    def post_commit_error(self): return self.manifest.get("post_commit_error")


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
        self._recover_pruning()
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
            version = db.execute("PRAGMA user_version").fetchone()[0]
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version > SCHEMA_VERSION:
                raise RecoverySchemaError(f"Journal schema {version} is newer than supported schema {SCHEMA_VERSION}.")
            if "transactions" not in tables:
                self._create_schema(db)
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                return
            # Revision 12.1 databases did not set user_version. Infer their schema.
            if version == 0:
                columns = {row[1] for row in db.execute("PRAGMA table_info(transactions)")}
                version = 2 if "undone_at" in columns else 1
            while version < SCHEMA_VERSION:
                with db:
                    if version == 1:
                        self._migrate_1_to_2(db)
                    elif version == 2:
                        self._migrate_2_to_3(db)
                    elif version == 3:
                        self._migrate_3_to_4(db)
                    elif version == 4:
                        self._migrate_4_to_5(db)
                    version += 1
                    db.execute(f"PRAGMA user_version = {version}")
            self._create_indexes(db)

    @staticmethod
    def _create_schema(db):
        db.executescript("""
            CREATE TABLE transactions (
                id TEXT PRIMARY KEY, timestamp_utc TEXT NOT NULL,
                operation TEXT NOT NULL, description TEXT NOT NULL,
                status TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0,
                committed_to_disk INTEGER NOT NULL DEFAULT 1,
                world_root TEXT NOT NULL, writer TEXT,
                location_before_json TEXT, location_after_json TEXT,
                committed_at TEXT, undone_at TEXT, redone_at TEXT,
                recovered_at TEXT, reviewed_at TEXT, superseded_at TEXT,
                error TEXT, post_commit_error TEXT, post_commit_error_at TEXT,
                damaged INTEGER NOT NULL DEFAULT 0,
                transaction_directory TEXT NOT NULL
            );
            CREATE TABLE pending_deletions (
                transaction_id TEXT PRIMARY KEY,
                original_status TEXT NOT NULL,
                claimed_at TEXT NOT NULL,
                FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE CASCADE
            );
            CREATE TABLE transaction_files (
                transaction_id TEXT NOT NULL, file_index INTEGER NOT NULL,
                absolute_path TEXT NOT NULL, relative_path TEXT NOT NULL,
                encoding TEXT, newline TEXT, mode INTEGER,
                before_exists INTEGER NOT NULL DEFAULT 1,
                after_exists INTEGER NOT NULL DEFAULT 1,
                before_sha256 TEXT, after_sha256 TEXT,
                before_snapshot TEXT, after_snapshot TEXT,
                PRIMARY KEY (transaction_id, file_index),
                FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE CASCADE
            );
        """)
        RecoveryJournal._create_indexes(db)

    @staticmethod
    def _create_indexes(db):
        db.executescript("""
            CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp_utc DESC);
            CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status);
            CREATE INDEX IF NOT EXISTS idx_transactions_undone ON transactions(undone_at DESC);
            CREATE INDEX IF NOT EXISTS idx_transactions_disk ON transactions(committed_to_disk, timestamp_utc);
            CREATE INDEX IF NOT EXISTS idx_transaction_files_path ON transaction_files(absolute_path);
        """)

    @staticmethod
    def _migrate_1_to_2(db):
        columns = {row[1] for row in db.execute("PRAGMA table_info(transactions)")}
        if "undone_at" not in columns: db.execute("ALTER TABLE transactions ADD COLUMN undone_at TEXT")
        if "redone_at" not in columns: db.execute("ALTER TABLE transactions ADD COLUMN redone_at TEXT")
        file_columns = {row[1] for row in db.execute("PRAGMA table_info(transaction_files)")}
        if "before_exists" not in file_columns: db.execute("ALTER TABLE transaction_files ADD COLUMN before_exists INTEGER NOT NULL DEFAULT 1")
        if "after_exists" not in file_columns: db.execute("ALTER TABLE transaction_files ADD COLUMN after_exists INTEGER NOT NULL DEFAULT 1")

    @staticmethod
    def _migrate_2_to_3(db):
        columns = {row[1] for row in db.execute("PRAGMA table_info(transactions)")}
        if "post_commit_error" not in columns: db.execute("ALTER TABLE transactions ADD COLUMN post_commit_error TEXT")
        if "post_commit_error_at" not in columns: db.execute("ALTER TABLE transactions ADD COLUMN post_commit_error_at TEXT")

    @staticmethod
    def _migrate_3_to_4(db):
        columns = {row[1] for row in db.execute("PRAGMA table_info(transactions)")}
        for name in ("recovered_at", "reviewed_at", "superseded_at"):
            if name not in columns:
                db.execute(f"ALTER TABLE transactions ADD COLUMN {name} TEXT")

    @staticmethod
    def _migrate_4_to_5(db):
        db.execute("CREATE TABLE IF NOT EXISTS pending_deletions (transaction_id TEXT PRIMARY KEY, original_status TEXT NOT NULL, claimed_at TEXT NOT NULL, FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE CASCADE)")

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
                    undone_at, redone_at, recovered_at, reviewed_at, superseded_at,
                    error, post_commit_error, post_commit_error_at, damaged, transaction_directory
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    recovered_at=excluded.recovered_at,
                    reviewed_at=excluded.reviewed_at,
                    superseded_at=excluded.superseded_at,
                    error=excluded.error,
                    post_commit_error=excluded.post_commit_error,
                    post_commit_error_at=excluded.post_commit_error_at,
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
                manifest.get("redone_at"), manifest.get("recovered_at"),
                manifest.get("reviewed_at"), manifest.get("superseded_at"), manifest.get("error"),
                manifest.get("post_commit_error"), manifest.get("post_commit_error_at"),
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
            "redone_at": row["redone_at"], "recovered_at": row["recovered_at"],
            "reviewed_at": row["reviewed_at"], "superseded_at": row["superseded_at"],
            "error": row["error"], "post_commit_error": row["post_commit_error"],
            "post_commit_error_at": row["post_commit_error_at"],
            "damaged": bool(row["damaged"]), "files": [{
                "path": item["absolute_path"], "relative_path": item["relative_path"],
                "encoding": item["encoding"], "newline": item["newline"], "mode": item["mode"],
                "before_exists": bool(item["before_exists"]), "after_exists": bool(item["after_exists"]),
                "before_sha256": item["before_sha256"], "after_sha256": item["after_sha256"],
                "before_snapshot": item["before_snapshot"], "after_snapshot": item["after_snapshot"],
            } for item in files],
        }

    def _snapshot_damage(self, directory, manifest):
        damaged = False
        status = manifest.get("status", "unknown")
        require_after = status in {
            TransactionStatus.COMMITTED.value, TransactionStatus.UNDONE.value,
            TransactionStatus.REDONE.value, TransactionStatus.SUPERSEDED.value,
        }
        for item in manifest.get("files", []):
            before_relative = item.get("before_snapshot")
            after_relative = item.get("after_snapshot")
            if before_relative and not (directory / before_relative).exists(): damaged = True
            if require_after and after_relative and not (directory / after_relative).exists(): damaged = True
        return damaged

    def _recover_pruning(self):
        with self._connect() as db:
            rows = db.execute("SELECT p.transaction_id, p.original_status, t.transaction_directory FROM pending_deletions p JOIN transactions t ON t.id = p.transaction_id").fetchall()
            for row in rows:
                directory = Path(row["transaction_directory"])
                if directory.exists():
                    db.execute("UPDATE transactions SET status = ? WHERE id = ? AND status = ?", (row["original_status"], row["transaction_id"], TransactionStatus.PRUNING.value))
                    db.execute("DELETE FROM pending_deletions WHERE transaction_id = ?", (row["transaction_id"],))
                else:
                    db.execute("DELETE FROM transactions WHERE id = ?", (row["transaction_id"],))

    def reconcile(self):
        """Use SQLite as authority; import JSON only when no database row exists."""
        manifest_entries = {}
        for directory in self.root.iterdir():
            manifest_path = directory / "manifest.json"
            if not directory.is_dir() or not manifest_path.exists(): continue
            try: manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError): continue
            manifest_entries[manifest.get("transaction_id", directory.name)] = (directory, manifest)
        with self._connect() as db:
            rows = db.execute("SELECT * FROM transactions").fetchall()
            database_ids = {row["id"] for row in rows}
            # Existing rows are authoritative. Repair mirror JSON from SQLite.
            for row in rows:
                files = db.execute("SELECT * FROM transaction_files WHERE transaction_id = ? ORDER BY file_index", (row["id"],)).fetchall()
                directory = Path(row["transaction_directory"])
                canonical = self._manifest_from_row(row, files)
                damaged = self._snapshot_damage(directory, canonical)
                if damaged != canonical.get("damaged", False):
                    db.execute("UPDATE transactions SET damaged = ? WHERE id = ?", (int(damaged), row["id"]))
                    canonical["damaged"] = damaged
                try:
                    current = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    current = None
                if current != canonical:
                    _json_write(directory / "manifest.json", canonical)
            # A portable JSON transaction absent from SQLite is a legacy import.
            for transaction_id, (directory, manifest) in manifest_entries.items():
                if transaction_id in database_ids: continue
                manifest.setdefault("format", FORMAT_VERSION)
                manifest.setdefault("committed_to_disk", True)
                manifest["damaged"] = self._snapshot_damage(directory, manifest)
                self._upsert_manifest(directory, manifest, db)
                _json_write(directory / "manifest.json", manifest)

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
        _write_durable_bytes(before_path, before)
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
        """Persist the core commit. Housekeeping failures become warnings."""
        _write_durable_bytes(after_path, after)
        manifest["status"] = TransactionStatus.COMMITTED.value
        manifest["committed_at"] = datetime.now(timezone.utc).isoformat()
        _json_write(directory / "manifest.json", manifest)
        self._upsert_manifest(directory, manifest)
        transaction = RecoveryTransaction(directory, manifest)
        warnings = []
        for label, action in (
            ("Redo history cleanup", lambda: self.supersede_redo_branch(excluding=manifest["transaction_id"])),
            ("Recovery retention cleanup", self.prune),
            ("History notification", self.emit_change),
        ):
            try: action()
            except Exception as exc: warnings.append(f"{label} failed: {exc}")
        return transaction, tuple(warnings)

    def emit_change(self):
        callback = getattr(self, "on_change", None)
        if callback: callback()

    def mark_failed(self, directory: Path, manifest: dict, message: str):
        manifest["status"] = "failed"
        manifest["error"] = message
        _json_write(directory / "manifest.json", manifest)
        self._upsert_manifest(directory, manifest)
        callback = getattr(self, "on_change", None)
        if callback:
            callback()

    def set_pinned(self, transaction: RecoveryTransaction, pinned: bool):
        manifest = dict(transaction.manifest); manifest["pinned"] = bool(pinned)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("UPDATE transactions SET pinned = ? WHERE id = ?", (int(bool(pinned)), transaction.transaction_id))
            if cursor.rowcount != 1:
                raise RecoveryConflictError("The transaction no longer exists.", transaction)
        _json_write(transaction.directory / "manifest.json", manifest)
        self.emit_change()

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

    def _transaction_from_row(self, db, row):
        if row is None: return None
        files = db.execute("SELECT * FROM transaction_files WHERE transaction_id = ? ORDER BY file_index", (row["id"],)).fetchall()
        return RecoveryTransaction(Path(row["transaction_directory"]), self._manifest_from_row(row, files))

    def get(self, transaction_id):
        with self._connect() as db:
            return self._transaction_from_row(db, db.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone())

    def latest_undo(self):
        with self._connect() as db:
            row = db.execute("SELECT * FROM transactions WHERE status IN (?, ?) AND damaged = 0 ORDER BY COALESCE(redone_at, committed_at, timestamp_utc) DESC LIMIT 1", (TransactionStatus.COMMITTED.value, TransactionStatus.REDONE.value)).fetchone()
            return self._transaction_from_row(db, row)

    def latest_redo(self):
        with self._connect() as db:
            row = db.execute("SELECT * FROM transactions WHERE status = ? AND damaged = 0 ORDER BY undone_at DESC LIMIT 1", (TransactionStatus.UNDONE.value,)).fetchone()
            return self._transaction_from_row(db, row)

    def set_status(self, transaction, status, expected_statuses=None, **extra):
        status = str(status)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM transactions WHERE id = ?", (transaction.transaction_id,)).fetchone()
            if row is None: raise RecoveryConflictError("The transaction no longer exists.", transaction)
            if expected_statuses and row["status"] not in set(expected_statuses):
                raise RecoveryConflictError(f"Transaction state changed from {transaction.status} to {row['status']}.", transaction)
            files = db.execute("SELECT * FROM transaction_files WHERE transaction_id = ? ORDER BY file_index", (transaction.transaction_id,)).fetchall()
            manifest = self._manifest_from_row(row, files)
            manifest["status"] = status; manifest.update(extra)
            self._upsert_manifest(transaction.directory, manifest, db)
        _json_write(transaction.directory / "manifest.json", manifest)
        self.emit_change()
        return RecoveryTransaction(transaction.directory, manifest)

    def supersede_redo_branch(self, excluding=None):
        now = datetime.now(timezone.utc).isoformat(); changed = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id, transaction_directory FROM transactions WHERE status = ? AND id != ?", (TransactionStatus.UNDONE.value, excluding or "")).fetchall()
            for row in rows:
                cursor = db.execute("UPDATE transactions SET status = ?, superseded_at = ? WHERE id = ? AND status = ?", (TransactionStatus.SUPERSEDED.value, now, row["id"], TransactionStatus.UNDONE.value))
                if cursor.rowcount == 1: changed.append((row["id"], Path(row["transaction_directory"])))
        for transaction_id, directory in changed:
            tx = self.get(transaction_id)
            if tx: _json_write(directory / "manifest.json", tx.manifest)

    def mark_post_commit_error(self, transaction, message):
        current = self.get(transaction.transaction_id) or transaction
        existing = current.post_commit_error
        combined = "\n".join(value for value in (existing, message) if value)
        return self.set_status(current, current.status, post_commit_error=combined, post_commit_error_at=datetime.now(timezone.utc).isoformat())

    def resolve_incomplete(self, transaction, action):
        states = {state for _path, state in self.inspect_state(transaction)}
        now = datetime.now(timezone.utc).isoformat()
        status = transaction.status
        if status in WRITE_INCOMPLETE_STATES:
            if action == "abort" and states == {"current equals before"}:
                return self.set_status(transaction, TransactionStatus.ABORTED.value, expected_statuses=WRITE_INCOMPLETE_STATES, recovered_at=now)
            if action == "finalize" and states == {"current equals after"}:
                for index, item in enumerate(transaction.files):
                    path = _transaction_path(item); current = path.read_bytes() if path.exists() else b""
                    if sha256_bytes(current) != item.get("after_sha256"): raise RecoveryConflictError("The current file no longer matches the intended after hash.", transaction)
                    after = self.snapshot_path(transaction, "after", index)
                    if not after.exists(): _write_durable_bytes(after, current)
                return self.set_status(transaction, TransactionStatus.COMMITTED.value, expected_statuses=WRITE_INCOMPLETE_STATES, recovered_at=now, committed_at=transaction.committed_at or now)
        elif status == TransactionStatus.UNDOING.value:
            if action == "abort" and states == {"current equals after"}:
                original = TransactionStatus.REDONE.value if transaction.redone_at else TransactionStatus.COMMITTED.value
                return self.set_status(transaction, original, expected_statuses={status}, recovered_at=now)
            if action == "finalize" and states == {"current equals before"}:
                return self.set_status(transaction, TransactionStatus.UNDONE.value, expected_statuses={status}, recovered_at=now, undone_at=transaction.undone_at or now)
        elif status == TransactionStatus.REDOING.value:
            if action == "abort" and states == {"current equals before"}:
                return self.set_status(transaction, TransactionStatus.UNDONE.value, expected_statuses={status}, recovered_at=now)
            if action == "finalize" and states == {"current equals after"}:
                return self.set_status(transaction, TransactionStatus.REDONE.value, expected_statuses={status}, recovered_at=now, redone_at=transaction.redone_at or now)
        if action == "review" and status in INCOMPLETE_STATES:
            return self.set_status(transaction, TransactionStatus.REVIEWED.value, expected_statuses=INCOMPLETE_STATES, reviewed_at=now)
        raise RecoveryConflictError("The selected recovery action is not safe for the current disk state.", transaction, self.inspect_state(transaction))

    def apply_transaction(self, transaction, direction):
        if direction not in {"undo", "redo"}: raise ValueError(direction)
        expected_statuses = {TransactionStatus.COMMITTED.value, TransactionStatus.REDONE.value} if direction == "undo" else {TransactionStatus.UNDONE.value}
        if transaction.status not in expected_statuses:
            raise RecoveryConflictError(f"Transaction {transaction.transaction_id} is {transaction.status}, so it cannot be {direction}ne.", transaction)
        if transaction.damaged: raise RecoveryConflictError("The transaction is damaged and cannot be applied automatically.", transaction)
        original_status = transaction.status
        claim_status = TransactionStatus.UNDOING.value if direction == "undo" else TransactionStatus.REDOING.value
        claimed = self.set_status(transaction, claim_status, expected_statuses=expected_statuses)
        source_side = "before" if direction == "undo" else "after"
        hash_key = "after_sha256" if direction == "undo" else "before_sha256"
        exists_key = "after_exists" if direction == "undo" else "before_exists"
        backups=[]; changed=[]
        try:
            conflicts=[]
            for index, (path, state) in enumerate(self.inspect_state(claimed)):
                item=claimed.manifest["files"][index]
                exists=item.get(exists_key, not (direction == "redo" and claimed.operation == OperationKind.CREATE_PACKAGE_INIT.value))
                expected=item.get(hash_key) if exists else None
                current=sha256_bytes(path.read_bytes()) if path.exists() else None
                if current != expected: conflicts.append((path,state))
            if conflicts:
                raise RecoveryConflictError(f"Cannot {direction} because {len(conflicts)} affected file(s) no longer match the expected hash.", claimed, conflicts)
            for index,item in enumerate(claimed.files):
                path=_transaction_path(item); existed=path.exists(); data=path.read_bytes() if existed else b""
                backups.append((path,existed,data,stat.S_IMODE(path.stat().st_mode) if existed else None))
                target_exists=item.get("before_exists", claimed.operation != OperationKind.CREATE_PACKAGE_INIT.value) if direction == "undo" else item.get("after_exists",True)
                if target_exists: _write_snapshot_to_disk(path,self.snapshot_path(claimed,source_side,index).read_bytes(),item.get("mode"))
                elif path.exists(): path.unlink(); _fsync_directory(path.parent)
                changed.append(path)
        except Exception:
            for path,existed,data,mode in reversed(backups):
                try:
                    if existed: _write_snapshot_to_disk(path,data,mode)
                    elif path.exists(): path.unlink()
                except OSError: pass
            current=self.get(claimed.transaction_id)
            if current and current.status == claim_status:
                self.set_status(current, original_status, expected_statuses={claim_status})
            raise
        now=datetime.now(timezone.utc).isoformat()
        current=self.get(claimed.transaction_id)
        if direction == "undo":
            result=self.set_status(current,TransactionStatus.UNDONE.value,expected_statuses={claim_status},undone_at=now)
        else:
            result=self.set_status(current,TransactionStatus.REDONE.value,expected_statuses={claim_status},redone_at=now)
        return result,tuple(changed)

    def database_settings(self):
        with self._connect() as db:
            return {
                "journal_mode": db.execute("PRAGMA journal_mode").fetchone()[0],
                "synchronous": db.execute("PRAGMA synchronous").fetchone()[0],
                "foreign_keys": db.execute("PRAGMA foreign_keys").fetchone()[0],
                "busy_timeout": db.execute("PRAGMA busy_timeout").fetchone()[0],
            }

    def prune(self):
        all_transactions=self.transactions(); latest_undo=self.latest_undo(); latest_redo=self.latest_redo()
        protected={item.transaction_id for item in all_transactions if item.pinned or item.status in INCOMPLETE_STATES or item.status == TransactionStatus.UNDONE.value}
        if latest_undo: protected.add(latest_undo.transaction_id)
        if latest_redo: protected.add(latest_redo.transaction_id)
        active=[item for item in all_transactions if item.status in {TransactionStatus.COMMITTED.value,TransactionStatus.REDONE.value}]
        protected.update(item.transaction_id for item in active[:self.max_transactions])
        completed=[item for item in all_transactions if item.status in TERMINAL_STATES and item.transaction_id not in protected]
        cutoff=datetime.now(timezone.utc)-timedelta(days=self.min_days)
        total=sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
        candidates=[]
        for item in reversed(completed):
            try: timestamp=datetime.fromisoformat(item.timestamp)
            except ValueError: timestamp=datetime.min.replace(tzinfo=timezone.utc)
            if not (len(all_transactions)-len(candidates)>self.max_transactions or total>self.max_bytes) or timestamp>cutoff: continue
            size=sum(path.stat().st_size for path in item.directory.rglob("*") if path.is_file())
            candidates.append((item,size)); total-=size
        if not candidates: return
        claimed=[]
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for item,size in candidates:
                cursor=db.execute("UPDATE transactions SET status = ? WHERE id = ? AND status = ?",(TransactionStatus.PRUNING.value,item.transaction_id,item.status))
                if cursor.rowcount==1:
                    db.execute("INSERT OR REPLACE INTO pending_deletions (transaction_id, original_status, claimed_at) VALUES (?, ?, ?)", (item.transaction_id, item.status, datetime.now(timezone.utc).isoformat()))
                    claimed.append((item,size))
        for item,_size in claimed:
            try:
                shutil.rmtree(item.directory)
            except OSError:
                with self._connect() as db:
                    db.execute("UPDATE transactions SET status = ? WHERE id = ? AND status = ?",(item.status,item.transaction_id,TransactionStatus.PRUNING.value))
                    db.execute("DELETE FROM pending_deletions WHERE transaction_id = ?", (item.transaction_id,))
                continue
            with self._connect() as db:
                db.execute("DELETE FROM transactions WHERE id = ? AND status = ?",(item.transaction_id,TransactionStatus.PRUNING.value))


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
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


