import json
from pathlib import Path

from pybrowser.parser import read_document
from pybrowser.recovery import RecoveryJournal, sha256_bytes
from pybrowser.source_write_service import SaveRequest, SourceWriteService


def test_journaled_write_records_snapshots_and_manifest(tmp_path):
    world = tmp_path / "world"; world.mkdir()
    path = world / "app.py"; path.write_bytes(b"VALUE = 1\n")
    doc = read_document(path)
    journal = RecoveryJournal(world, tmp_path / "history")
    tx = SourceWriteService(journal).save_document(SaveRequest(doc, "VALUE = 2\n", "save_member", "Save Member VALUE")).transaction
    assert path.read_bytes() == b"VALUE = 2\n"
    manifest = json.loads((tx.directory / "manifest.json").read_text())
    assert manifest["status"] == "committed"
    assert manifest["operation"] == "save_member"
    assert journal.snapshot_path(tx, "before").read_bytes() == b"VALUE = 1\n"
    assert journal.snapshot_path(tx, "after").read_bytes() == b"VALUE = 2\n"
    assert manifest["files"][0]["before_sha256"] == sha256_bytes(b"VALUE = 1\n")


def test_incomplete_transaction_scan_and_disk_state(tmp_path):
    world = tmp_path / "world"; world.mkdir()
    path = world / "app.py"; path.write_text("A = 1\n")
    journal = RecoveryJournal(world, tmp_path / "history")
    directory, manifest, _after = journal.record_write(path, path.read_bytes(), b"A = 2\n", operation="save_file")
    incomplete = journal.incomplete()
    assert len(incomplete) == 1
    assert incomplete[0].status == "committing"
    assert journal.inspect_state(incomplete[0])[0][1] == "current equals before"


def test_restore_as_and_pinning(tmp_path):
    world = tmp_path / "world"; world.mkdir()
    path = world / "app.py"; path.write_text("A = 1\n")
    journal = RecoveryJournal(world, tmp_path / "history")
    tx = SourceWriteService(journal).save_document(SaveRequest(read_document(path), "A = 2\n", "save_file", "Save File")).transaction
    restored = tmp_path / "restored.py"
    journal.restore_as(tx, "before", restored)
    assert restored.read_text() == "A = 1\n"
    journal.set_pinned(tx, True)
    assert journal.transactions()[0].pinned


def test_journaled_new_file_has_empty_before_snapshot(tmp_path):
    world = tmp_path / "world"; world.mkdir()
    journal = RecoveryJournal(world, tmp_path / "history")
    path = world / "pkg" / "__init__.py"
    tx = SourceWriteService(journal).create_file(path, b'"""Package."""\n', operation="create_package_init").transaction
    assert path.exists()
    assert journal.snapshot_path(tx, "before").read_bytes() == b""
    assert journal.snapshot_path(tx, "after").read_bytes() == b'"""Package."""\n'


def test_sqlite_is_authoritative_index_with_durable_pragmas(tmp_path):
    import sqlite3
    world = tmp_path / "world"; world.mkdir()
    path = world / "app.py"; path.write_text("A = 1\n")
    journal = RecoveryJournal(world, tmp_path / "history")
    tx = SourceWriteService(journal).save_document(SaveRequest(read_document(path), "A = 2\n", "save_member", "Save Member")).transaction
    assert journal.database_path.exists()
    settings = journal.database_settings()
    assert settings["journal_mode"].casefold() == "wal"
    assert settings["synchronous"] == 2  # SQLITE_FULL
    assert settings["foreign_keys"] == 1
    assert settings["busy_timeout"] == 5000
    with sqlite3.connect(journal.database_path) as db:
        assert db.execute("SELECT status FROM transactions WHERE id = ?", (tx.transaction_id,)).fetchone()[0] == "committed"
        assert db.execute("SELECT absolute_path FROM transaction_files WHERE transaction_id = ?", (tx.transaction_id,)).fetchone()[0] == str(path.resolve())


def test_legacy_json_manifest_is_imported_into_sqlite(tmp_path):
    import json
    world = tmp_path / "world"; world.mkdir()
    path = world / "app.py"; path.write_text("A = 2\n")
    history_root = tmp_path / "history"
    journal = RecoveryJournal(world, history_root)
    tx_dir = journal.root / "legacy-transaction"
    before = tx_dir / "before" / "app.py"; after = tx_dir / "after" / "app.py"
    before.parent.mkdir(parents=True); after.parent.mkdir(parents=True)
    before.write_text("A = 1\n"); after.write_text("A = 2\n")
    manifest = {
        "format": 1, "transaction_id": "legacy-transaction",
        "timestamp": "2026-11-06T10:00:00+00:00", "operation": "save_member",
        "description": "Legacy save", "status": "committed", "pinned": False,
        "world_root": str(world.resolve()), "files": [{
            "path": str(path.resolve()), "relative_path": "app.py", "encoding": "utf-8",
            "newline": "LF", "mode": 420,
            "before_sha256": sha256_bytes(b"A = 1\n"), "after_sha256": sha256_bytes(b"A = 2\n"),
            "before_snapshot": "before/app.py", "after_snapshot": "after/app.py",
        }],
    }
    (tx_dir / "manifest.json").write_text(json.dumps(manifest))
    reopened = RecoveryJournal(world, history_root)
    imported = next(item for item in reopened.transactions() if item.transaction_id == "legacy-transaction")
    assert imported.description == "Legacy save"
    assert not imported.damaged


def test_reconcile_marks_missing_snapshot_as_damaged(tmp_path):
    import json
    world = tmp_path / "world"; world.mkdir()
    path = world / "app.py"; path.write_text("A = 1\n")
    journal = RecoveryJournal(world, tmp_path / "history")
    tx_dir = journal.root / "damaged-transaction"; tx_dir.mkdir()
    manifest = {
        "format": 1, "transaction_id": "damaged-transaction",
        "timestamp": "2026-11-06T11:00:00+00:00", "operation": "save_file",
        "description": "Damaged save", "status": "committed", "pinned": False,
        "world_root": str(world.resolve()), "files": [{
            "path": str(path.resolve()), "relative_path": "app.py", "encoding": "utf-8",
            "newline": "LF", "before_sha256": "x", "after_sha256": "y",
            "before_snapshot": "before/app.py", "after_snapshot": "after/app.py",
        }],
    }
    (tx_dir / "manifest.json").write_text(json.dumps(manifest))
    reopened = RecoveryJournal(world, tmp_path / "history")
    damaged = next(item for item in reopened.transactions() if item.transaction_id == "damaged-transaction")
    assert damaged.damaged


def test_sqlite_pinning_and_incomplete_queries_stay_in_sync(tmp_path):
    world = tmp_path / "world"; world.mkdir()
    path = world / "app.py"; path.write_text("A = 1\n")
    journal = RecoveryJournal(world, tmp_path / "history")
    directory, manifest, _after = journal.record_write(path, path.read_bytes(), b"A = 2\n")
    tx = journal.incomplete()[0]
    journal.set_pinned(tx, True)
    reloaded = next(item for item in journal.transactions() if item.transaction_id == tx.transaction_id)
    assert reloaded.pinned
    assert reloaded.status == "committing"


def test_safe_undo_and_redo_round_trip(tmp_path):
    world = tmp_path / "world"; world.mkdir()
    path = world / "app.py"; path.write_text("A = 1\n")
    journal = RecoveryJournal(world, tmp_path / "history")
    tx = SourceWriteService(journal).save_document(SaveRequest(read_document(path), "A = 2\n", "save_member", "Save Member")).transaction
    undone, paths = journal.apply_transaction(tx, "undo")
    assert path.read_text() == "A = 1\n"
    assert undone.status == "undone"
    assert paths == (path.resolve(),)
    redone, _ = journal.apply_transaction(undone, "redo")
    assert path.read_text() == "A = 2\n"
    assert redone.status == "redone"
    assert journal.latest_undo().transaction_id == tx.transaction_id


def test_undo_refuses_hash_mismatch_without_writing(tmp_path):
    from pybrowser.recovery import RecoveryConflictError
    world = tmp_path / "world"; world.mkdir()
    path = world / "app.py"; path.write_text("A = 1\n")
    journal = RecoveryJournal(world, tmp_path / "history")
    tx = SourceWriteService(journal).save_document(SaveRequest(read_document(path), "A = 2\n", "save_file", "Save File")).transaction
    path.write_text("EXTERNAL = 3\n")
    try:
        journal.apply_transaction(tx, "undo")
    except RecoveryConflictError as exc:
        assert exc.states
    else:
        raise AssertionError("Expected RecoveryConflictError")
    assert path.read_text() == "EXTERNAL = 3\n"
    assert journal.get(tx.transaction_id).status == "committed"


def test_undo_new_file_deletes_and_redo_recreates(tmp_path):
    world = tmp_path / "world"; world.mkdir()
    journal = RecoveryJournal(world, tmp_path / "history")
    path = world / "pkg" / "__init__.py"
    tx = SourceWriteService(journal).create_file(path, b'"""Package."""\n', operation="create_package_init").transaction
    undone, _ = journal.apply_transaction(tx, "undo")
    assert not path.exists()
    redone, _ = journal.apply_transaction(undone, "redo")
    assert path.read_bytes() == b'"""Package."""\n'
    assert redone.status == "redone"


def test_undo_redo_status_persists_in_sqlite_and_manifest(tmp_path):
    world = tmp_path / "world"; world.mkdir()
    path = world / "app.py"; path.write_text("A = 1\n")
    history = tmp_path / "history"
    journal = RecoveryJournal(world, history)
    tx = SourceWriteService(journal).save_document(SaveRequest(read_document(path), "A = 2\n", "save_file", "Save File")).transaction
    undone, _ = journal.apply_transaction(tx, "undo")
    manifest = json.loads((tx.directory / "manifest.json").read_text())
    assert manifest["status"] == "undone"
    assert manifest["undone_at"]
    reopened = RecoveryJournal(world, history)
    reloaded = reopened.get(tx.transaction_id)
    assert reloaded.status == "undone"
    assert reopened.latest_redo().transaction_id == tx.transaction_id

def test_redo_uses_most_recent_undo_order(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 0\n')
    journal=RecoveryJournal(world,tmp_path/'history'); service=SourceWriteService(journal)
    first=service.save_document(SaveRequest(read_document(path),'A = 1\n','save_file','one')).transaction
    second=service.save_document(SaveRequest(read_document(path),'A = 2\n','save_file','two')).transaction
    second_undone,_=journal.apply_transaction(second,'undo')
    first_undone,_=journal.apply_transaction(first,'undo')
    assert journal.latest_redo().transaction_id == first.transaction_id
    first_redone,_=journal.apply_transaction(first_undone,'redo')
    assert path.read_text() == 'A = 1\n'
    assert journal.latest_redo().transaction_id == second.transaction_id

def test_new_commit_supersedes_redo_branch(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 0\n')
    journal=RecoveryJournal(world,tmp_path/'history'); service=SourceWriteService(journal)
    old=service.save_document(SaveRequest(read_document(path),'A = 1\n','save_file','old')).transaction
    undone,_=journal.apply_transaction(old,'undo')
    service.save_document(SaveRequest(read_document(path),'A = 2\n','save_file','branch'))
    assert journal.get(old.transaction_id).status == 'superseded'
    assert journal.latest_redo() is None

def test_incomplete_resolution_actions(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    journal=RecoveryJournal(world,tmp_path/'history')
    directory,manifest,after=journal.record_write(path,path.read_bytes(),b'A = 2\n')
    tx=journal.incomplete()[0]
    assert journal.resolve_incomplete(tx,'abort').status == 'aborted'
    directory,manifest,after=journal.record_write(path,path.read_bytes(),b'A = 2\n')
    path.write_bytes(b'A = 2\n'); after.parent.mkdir(parents=True,exist_ok=True); after.write_bytes(b'A = 2\n')
    tx=journal.incomplete()[0]
    assert journal.resolve_incomplete(tx,'finalize').status == 'committed'

def test_schema_user_version_is_current(tmp_path):
    world=tmp_path/'world'; world.mkdir(); journal=RecoveryJournal(world,tmp_path/'history')
    import sqlite3
    with sqlite3.connect(journal.database_path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 6

def _create_legacy_database(path, version):
    import sqlite3
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE transactions (
                id TEXT PRIMARY KEY, timestamp_utc TEXT NOT NULL, operation TEXT NOT NULL,
                description TEXT NOT NULL, status TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0,
                committed_to_disk INTEGER NOT NULL DEFAULT 1, world_root TEXT NOT NULL,
                writer TEXT, location_before_json TEXT, location_after_json TEXT,
                committed_at TEXT, error TEXT, damaged INTEGER NOT NULL DEFAULT 0,
                transaction_directory TEXT NOT NULL
            );
            CREATE TABLE transaction_files (
                transaction_id TEXT NOT NULL, file_index INTEGER NOT NULL,
                absolute_path TEXT NOT NULL, relative_path TEXT NOT NULL,
                encoding TEXT, newline TEXT, mode INTEGER, before_sha256 TEXT,
                after_sha256 TEXT, before_snapshot TEXT, after_snapshot TEXT,
                PRIMARY KEY (transaction_id, file_index)
            );
        ''')
        if version >= 2:
            db.execute('ALTER TABLE transactions ADD COLUMN undone_at TEXT')
            db.execute('ALTER TABLE transactions ADD COLUMN redone_at TEXT')
            db.execute('ALTER TABLE transaction_files ADD COLUMN before_exists INTEGER NOT NULL DEFAULT 1')
            db.execute('ALTER TABLE transaction_files ADD COLUMN after_exists INTEGER NOT NULL DEFAULT 1')
        db.execute(f'PRAGMA user_version = {version}')


def test_real_schema_1_and_2_databases_migrate(tmp_path):
    import sqlite3
    from pybrowser.recovery import world_id
    for version in (1, 2):
        world = tmp_path / f'world{version}'; world.mkdir()
        history = tmp_path / f'history{version}'; root = history / world_id(world); root.mkdir(parents=True)
        (root / 'world.json').write_text('{}')
        _create_legacy_database(root / 'journal.sqlite3', version)
        journal = RecoveryJournal(world, history)
        with sqlite3.connect(journal.database_path) as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == 6
            columns = {row[1] for row in db.execute('PRAGMA table_info(transactions)')}
            assert {'undone_at', 'redone_at', 'post_commit_error', 'post_commit_error_at'} <= columns
            indexes = {row[1] for row in db.execute('PRAGMA index_list(transactions)')}
            assert 'idx_transactions_undone' in indexes


def test_incomplete_restart_is_not_damaged_without_after_snapshot(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    history=tmp_path/'history'; journal=RecoveryJournal(world,history)
    directory,manifest,after=journal.record_write(path,path.read_bytes(),b'A = 2\n')
    assert not after.exists()
    reopened=RecoveryJournal(world,history)
    tx=reopened.incomplete()[0]
    assert not tx.damaged


def test_finalize_incomplete_reconstructs_missing_after_snapshot(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    history=tmp_path/'history'; journal=RecoveryJournal(world,history)
    directory,manifest,after=journal.record_write(path,path.read_bytes(),b'A = 2\n')
    path.write_bytes(b'A = 2\n')
    reopened=RecoveryJournal(world,history); tx=reopened.incomplete()[0]
    assert not reopened.snapshot_path(tx,'after').exists()
    result=reopened.resolve_incomplete(tx,'finalize')
    assert result.status == 'committed'
    assert reopened.snapshot_path(result,'after').read_bytes() == b'A = 2\n'


def test_new_commit_is_committed_before_redo_branch_superseded(tmp_path, monkeypatch):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 0\n')
    journal=RecoveryJournal(world,tmp_path/'history'); service=SourceWriteService(journal)
    old=service.save_document(SaveRequest(read_document(path),'A = 1\n','save_file','old')).transaction
    journal.apply_transaction(old,'undo')
    original=journal.supersede_redo_branch
    observed=[]
    def inspect(excluding=None):
        observed.append(journal.get(excluding).status)
        return original(excluding)
    monkeypatch.setattr(journal,'supersede_redo_branch',inspect)
    service.save_document(SaveRequest(read_document(path),'A = 2\n','save_file','new'))
    assert observed == ['committed']

def test_sqlite_repairs_stale_json_without_reactivating_redo(tmp_path):
    import sqlite3
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 0\n')
    history=tmp_path/'history'; journal=RecoveryJournal(world,history); service=SourceWriteService(journal)
    tx=service.save_document(SaveRequest(read_document(path),'A = 1\n','save_file','one')).transaction
    undone,_=journal.apply_transaction(tx,'undo')
    service.save_document(SaveRequest(read_document(path),'A = 2\n','save_file','branch'))
    stale=json.loads((tx.directory/'manifest.json').read_text()); stale['status']='undone'; stale['pinned']=False
    (tx.directory/'manifest.json').write_text(json.dumps(stale))
    with sqlite3.connect(journal.database_path) as db:
        db.execute('UPDATE transactions SET pinned = 1 WHERE id = ?', (tx.transaction_id,))
    reopened=RecoveryJournal(world,history)
    repaired=json.loads((tx.directory/'manifest.json').read_text())
    assert reopened.get(tx.transaction_id).status == 'superseded'
    assert repaired['status'] == 'superseded'
    assert repaired['pinned'] is True
    assert reopened.latest_redo() is None


def test_missing_json_is_rebuilt_from_sqlite(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    history=tmp_path/'history'; journal=RecoveryJournal(world,history)
    tx=SourceWriteService(journal).save_document(SaveRequest(read_document(path),'A = 2\n','save_file','save')).transaction
    (tx.directory/'manifest.json').unlink()
    RecoveryJournal(world,history)
    assert json.loads((tx.directory/'manifest.json').read_text())['status'] == 'committed'


def test_retention_prunes_old_committed_history_but_keeps_latest(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 0\n')
    journal=RecoveryJournal(world,tmp_path/'history',max_transactions=2,min_days=0,max_megabytes=500)
    service=SourceWriteService(journal)
    ids=[]
    for value in range(1,6):
        ids.append(service.save_document(SaveRequest(read_document(path),f'A = {value}\n','save_file',str(value))).transaction.transaction_id)
    remaining={tx.transaction_id for tx in journal.transactions()}
    assert ids[-1] in remaining
    assert len(remaining) <= 2

def test_schema_4_preserves_recovery_review_and_supersede_timestamps(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    history=tmp_path/'history'; journal=RecoveryJournal(world,history)
    directory,manifest,_=journal.record_write(path,path.read_bytes(),b'A = 2\n')
    aborted=journal.resolve_incomplete(journal.incomplete()[0],'abort')
    reopened=RecoveryJournal(world,history)
    assert reopened.get(aborted.transaction_id).recovered_at
    directory,manifest,_=reopened.record_write(path,path.read_bytes(),b'A = 3\n')
    reviewed=reopened.resolve_incomplete(reopened.incomplete()[0],'review')
    again=RecoveryJournal(world,history)
    assert again.get(reviewed.transaction_id).manifest['reviewed_at']
    tx=SourceWriteService(again).save_document(SaveRequest(read_document(path),'A = 4\n','save_file','one')).transaction
    undone,_=again.apply_transaction(tx,'undo')
    SourceWriteService(again).save_document(SaveRequest(read_document(path),'A = 5\n','save_file','branch'))
    final=RecoveryJournal(world,history).get(tx.transaction_id)
    assert final.status == 'superseded' and final.manifest['superseded_at']


def test_rebuilt_manifest_uses_portable_file_shape(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    history=tmp_path/'history'; journal=RecoveryJournal(world,history)
    tx=SourceWriteService(journal).save_document(SaveRequest(read_document(path),'A = 2\n','save_file','save')).transaction
    (tx.directory/'manifest.json').unlink(); RecoveryJournal(world,history)
    item=json.loads((tx.directory/'manifest.json').read_text())['files'][0]
    assert set(item) == {'path','relative_path','encoding','newline','mode','before_exists','after_exists','before_sha256','after_sha256','before_snapshot','after_snapshot'}
    assert 'transaction_id' not in item and 'file_index' not in item and 'absolute_path' not in item


def test_undo_claim_blocks_second_journal_before_source_write(tmp_path, monkeypatch):
    from pybrowser.recovery import RecoveryConflictError, TransactionStatus
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    history=tmp_path/'history'; first=RecoveryJournal(world,history)
    tx=SourceWriteService(first).save_document(SaveRequest(read_document(path),'A = 2\n','save_file','save')).transaction
    claimed=first.set_status(tx,TransactionStatus.UNDOING.value,expected_statuses={'committed'})
    second=RecoveryJournal(world,history)
    with __import__('pytest').raises(RecoveryConflictError): second.apply_transaction(tx,'undo')
    first.set_status(claimed,'committed',expected_statuses={'undoing'})
    assert path.read_text() == 'A = 2\n'

def test_interrupted_undo_claim_can_roll_back_or_finalize_after_restart(tmp_path):
    from pybrowser.recovery import TransactionStatus
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    history=tmp_path/'history'; journal=RecoveryJournal(world,history)
    tx=SourceWriteService(journal).save_document(SaveRequest(read_document(path),'A = 2\n','save_file','save')).transaction
    claimed=journal.set_status(tx,TransactionStatus.UNDOING.value,expected_statuses={'committed'})
    reopened=RecoveryJournal(world,history); found=reopened.incomplete()[0]
    assert found.status == 'undoing'
    assert reopened.resolve_incomplete(found,'abort').status == 'committed'
    claimed=reopened.set_status(reopened.get(tx.transaction_id),'undoing',expected_statuses={'committed'})
    path.write_text('A = 1\n')
    finalized=RecoveryJournal(world,history).resolve_incomplete(RecoveryJournal(world,history).get(tx.transaction_id),'finalize')
    assert finalized.status == 'undone'


def test_interrupted_redo_claim_can_roll_back_or_finalize_after_restart(tmp_path):
    from pybrowser.recovery import TransactionStatus
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    history=tmp_path/'history'; journal=RecoveryJournal(world,history)
    tx=SourceWriteService(journal).save_document(SaveRequest(read_document(path),'A = 2\n','save_file','save')).transaction
    undone,_=journal.apply_transaction(tx,'undo')
    claimed=journal.set_status(undone,TransactionStatus.REDOING.value,expected_statuses={'undone'})
    reopened=RecoveryJournal(world,history); assert reopened.resolve_incomplete(reopened.get(tx.transaction_id),'abort').status == 'undone'
    claimed=reopened.set_status(reopened.get(tx.transaction_id),'redoing',expected_statuses={'undone'})
    path.write_bytes(reopened.snapshot_path(claimed, 'after').read_bytes())
    final_journal = RecoveryJournal(world, history)
    assert final_journal.resolve_incomplete(final_journal.get(tx.transaction_id), 'finalize').status == 'redone'


def test_pruning_recovery_restores_existing_directory_and_deletes_missing(tmp_path):
    import sqlite3
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    history=tmp_path/'history'; journal=RecoveryJournal(world,history)
    tx=SourceWriteService(journal).save_document(SaveRequest(read_document(path),'A = 2\n','save_file','save')).transaction
    with sqlite3.connect(journal.database_path) as db:
        db.execute("UPDATE transactions SET status='pruning' WHERE id=?",(tx.transaction_id,))
        db.execute("INSERT INTO pending_deletions VALUES (?, ?, ?)",(tx.transaction_id,'committed','now'))
    assert RecoveryJournal(world,history).get(tx.transaction_id).status == 'committed'
    with sqlite3.connect(journal.database_path) as db:
        db.execute("UPDATE transactions SET status='pruning' WHERE id=?",(tx.transaction_id,))
        db.execute("INSERT INTO pending_deletions VALUES (?, ?, ?)",(tx.transaction_id,'committed','now'))
    import shutil; shutil.rmtree(tx.directory)
    reopened=RecoveryJournal(world,history)
    assert reopened.get(tx.transaction_id) is None and not tx.directory.exists()


def test_status_transition_preserves_newer_pin_metadata(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    journal=RecoveryJournal(world,tmp_path/'history')
    stale=SourceWriteService(journal).save_document(SaveRequest(read_document(path),'A = 2\n','save_file','save')).transaction
    journal.set_pinned(stale,True)
    updated=journal.set_status(stale,'redone',expected_statuses={'committed'})
    assert updated.pinned is True


def test_post_commit_warnings_accumulate(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    journal=RecoveryJournal(world,tmp_path/'history')
    tx=SourceWriteService(journal).save_document(SaveRequest(read_document(path),'A = 2\n','save_file','save')).transaction
    tx=journal.mark_post_commit_error(tx,'first')
    tx=journal.mark_post_commit_error(tx,'second')
    assert tx.post_commit_error == 'first\nsecond'

def test_pinning_stale_transaction_writes_authoritative_json(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    journal=RecoveryJournal(world,tmp_path/'history')
    stale=SourceWriteService(journal).save_document(SaveRequest(read_document(path),'A = 2\n','save_file','save')).transaction
    current=journal.mark_post_commit_error(stale,'new warning')
    pinned=journal.set_pinned(stale,True)
    mirror=json.loads((stale.directory/'manifest.json').read_text())
    assert pinned.pinned and mirror['pinned'] is True
    assert mirror['post_commit_error'] == 'new warning'


def test_history_transient_state_requires_after_snapshot(tmp_path):
    from pybrowser.recovery import TransactionStatus
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    history=tmp_path/'history'; journal=RecoveryJournal(world,history)
    tx=SourceWriteService(journal).save_document(SaveRequest(read_document(path),'A = 2\n','save_file','save')).transaction
    claimed=journal.set_status(tx,TransactionStatus.UNDOING.value,expected_statuses={'committed'})
    journal.snapshot_path(claimed,'after').unlink()
    reopened=RecoveryJournal(world,history)
    assert reopened.get(tx.transaction_id).damaged


def test_update_prepared_rebuilds_json_from_sqlite(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'new.py'
    journal=RecoveryJournal(world,tmp_path/'history')
    directory,manifest,_after=journal.record_write(path,b'',b'A = 1\n')
    manifest['files'][0]['before_exists']=False
    journal.update_prepared(directory,manifest)
    mirror=json.loads((directory/'manifest.json').read_text())
    assert mirror['files'][0]['before_exists'] is False
    assert journal.get(manifest['transaction_id']).files[0]['before_exists'] is False


def test_undo_uses_same_path_lock_as_source_writes(tmp_path):
    from pybrowser.recovery import RecoveryConflictError
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_text('A = 1\n')
    journal=RecoveryJournal(world,tmp_path/'history')
    tx=SourceWriteService(journal).save_document(SaveRequest(read_document(path),'A = 2\n','save_file','save')).transaction
    with journal.locks.acquire(path):
        with __import__('pytest').raises(RecoveryConflictError):
            journal.apply_transaction(tx,'undo')
    assert path.read_text() == 'A = 2\n'
    assert journal.get(tx.transaction_id).status == 'committed'


def test_multi_path_locks_use_canonical_order_and_deduplicate(tmp_path):
    from pybrowser.path_locks import PathLockService
    locks=PathLockService(tmp_path/'locks')
    first=tmp_path/'z.py'; second=tmp_path/'A.py'
    with locks.acquire_many([first, second, first]) as acquired:
        assert acquired == tuple(sorted({first.resolve(), second.resolve()}, key=lambda p: str(p).casefold()))
        assert len(list((tmp_path/'locks').glob('*.lock'))) == 2
    assert list((tmp_path/'locks').glob('*.lock')) == []


def test_manifest_hashes_exact_snapshot_bytes(tmp_path):
    world = tmp_path / "world"; world.mkdir()
    path = world / "app.py"; path.write_bytes(b"A = 1\r\n")
    journal = RecoveryJournal(world, tmp_path / "history")
    tx = SourceWriteService(journal).save_document(
        SaveRequest(read_document(path), "A = 2\r\n", "save_file", "save")
    ).transaction
    before = journal.snapshot_path(tx, "before").read_bytes()
    after = journal.snapshot_path(tx, "after").read_bytes()
    assert tx.files[0]["before_sha256"] == sha256_bytes(before)
    assert tx.files[0]["after_sha256"] == sha256_bytes(after)
    assert path.read_bytes() == after
