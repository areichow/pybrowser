import json
from pathlib import Path

from pybrowser.parser import read_document
from pybrowser.recovery import RecoveryJournal, journaled_atomic_write, journaled_create_file, sha256_bytes


def test_journaled_write_records_snapshots_and_manifest(tmp_path):
    world = tmp_path / "world"; world.mkdir()
    path = world / "app.py"; path.write_text("VALUE = 1\n")
    doc = read_document(path)
    journal = RecoveryJournal(world, tmp_path / "history")
    tx = journaled_atomic_write(doc, "VALUE = 2\n", journal, operation="save_member", description="Save Member VALUE")
    assert path.read_text() == "VALUE = 2\n"
    manifest = json.loads((tx.directory / "manifest.json").read_text())
    assert manifest["status"] == "committed"
    assert manifest["operation"] == "save_member"
    assert journal.snapshot_path(tx, "before").read_text() == "VALUE = 1\n"
    assert journal.snapshot_path(tx, "after").read_text() == "VALUE = 2\n"
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
    tx = journaled_atomic_write(read_document(path), "A = 2\n", journal)
    restored = tmp_path / "restored.py"
    journal.restore_as(tx, "before", restored)
    assert restored.read_text() == "A = 1\n"
    journal.set_pinned(tx, True)
    assert journal.transactions()[0].pinned


def test_journaled_new_file_has_empty_before_snapshot(tmp_path):
    world = tmp_path / "world"; world.mkdir()
    journal = RecoveryJournal(world, tmp_path / "history")
    path = world / "pkg" / "__init__.py"
    tx = journaled_create_file(path, b'"""Package."""\n', journal, operation="create_package_init")
    assert path.exists()
    assert journal.snapshot_path(tx, "before").read_bytes() == b""
    assert journal.snapshot_path(tx, "after").read_bytes() == b'"""Package."""\n'
