import pytest
pytest.importorskip("PySide6")

from pybrowser.parser import read_document
from pybrowser.recovery import RecoveryJournal
from pybrowser.source_write_service import SaveRequest, SourceWriteService, WriteMode
from pybrowser.widgets.staged_changes import StagedChangesWindow
from pybrowser.world_source import WorldSourceStore


def test_staged_change_conflict_classification(tmp_path):
    path = tmp_path / "app.py"
    path.write_bytes(b"A = 1\n")
    from pybrowser.saving import stable_read
    baseline = stable_read(path).signature
    assert StagedChangesWindow._conflict(path, baseline, True) == (
        False, "Physical file still matches the staged baseline")
    path.write_bytes(b"A = 9\n")
    conflict, detail = StagedChangesWindow._conflict(path, baseline, True)
    assert conflict and "differs" in detail


def test_virtual_file_conflict_classification(tmp_path):
    path = tmp_path / "new.py"
    assert StagedChangesWindow._conflict(path, None, False) == (
        False, "Virtual target is still absent from disk")
    path.write_bytes(b"EXTERNAL = 1\n")
    conflict, detail = StagedChangesWindow._conflict(path, None, False)
    assert conflict and "now exists" in detail


def test_active_overlay_supplies_staged_window_metadata(tmp_path):
    world = tmp_path / "world"; world.mkdir()
    path = world / "app.py"; path.write_bytes(b"A = 1\n")
    journal = RecoveryJournal(world, tmp_path / "history")
    store = WorldSourceStore(world, journal.locks)
    service = SourceWriteService(journal, source_store=store,
                                 write_mode=WriteMode.MANUAL_COMMIT)
    staged = service.save_document(SaveRequest(
        read_document(path), "A = 2\n", "save_file", "Stage app"))
    active_path, transaction, disk_signature = journal.active_overlays()[0]
    assert active_path == path.resolve()
    assert transaction.transaction_id == staged.transaction.transaction_id
    assert transaction.description == "Stage app"
    assert disk_signature == read_document(path).signature
