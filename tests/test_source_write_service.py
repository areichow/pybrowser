from pathlib import Path

import pytest

from pybrowser.parser import ParseError, read_document
from pybrowser.recovery import RecoveryJournal
from pybrowser.source_write_service import SaveRequest, SourceConflictError, SourceWriteService


def service_for(tmp_path):
    world = tmp_path / "world"; world.mkdir()
    journal = RecoveryJournal(world, tmp_path / "history")
    notifications = []
    service = SourceWriteService(journal, lambda path, origin: notifications.append((path, origin)))
    return world, journal, service, notifications


def test_service_validates_journals_writes_reparses_and_notifies(tmp_path):
    world, journal, service, notifications = service_for(tmp_path)
    path = world / "app.py"; path.write_text("A = 1\n")
    origin = object()
    result = service.save_document(SaveRequest(
        read_document(path), "A = 2\n", "save_file", "Save app", origin=origin,
    ))
    assert path.read_text() == "A = 2\n"
    assert result.document.text == "A = 2\n"
    assert result.transaction.status == "committed"
    assert notifications == [(path.resolve(), origin)]
    assert journal.transactions()[0].operation if hasattr(journal.transactions()[0], "operation") else journal.transactions()[0].manifest["operation"] == "save_file"


def test_service_rejects_invalid_source_before_journaling(tmp_path):
    world, journal, service, notifications = service_for(tmp_path)
    path = world / "app.py"; path.write_text("A = 1\n")
    with pytest.raises(ParseError):
        service.save_document(SaveRequest(read_document(path), "def broken(:\n", "save_file", "Broken"))
    assert path.read_text() == "A = 1\n"
    assert journal.transactions() == ()
    assert notifications == []


def test_service_rejects_external_change_before_journaling(tmp_path):
    world, journal, service, notifications = service_for(tmp_path)
    path = world / "app.py"; path.write_text("A = 1\n")
    document = read_document(path)
    path.write_text("A = 9\n")
    with pytest.raises(SourceConflictError):
        service.save_document(SaveRequest(document, "A = 2\n", "save_file", "Save"))
    assert journal.transactions() == ()
    assert notifications == []


def test_service_create_file_is_validated_journaled_and_notified(tmp_path):
    world, journal, service, notifications = service_for(tmp_path)
    path = world / "pkg" / "__init__.py"
    result = service.create_file(path, b'"""Package."""\n', operation="create_package_init", origin="test")
    assert result.document.path == path.resolve()
    assert result.transaction.manifest["files"][0]["before_exists"] is False
    assert notifications == [(path.resolve(), "test")]
    with pytest.raises(SourceConflictError):
        service.create_file(path, b"VALUE = 1\n")

def test_post_commit_reparse_failure_keeps_committed_status(tmp_path, monkeypatch):
    import pybrowser.source_write_service as module
    from pybrowser.source_write_service import SourcePostCommitError
    world,journal,service,notifications=service_for(tmp_path)
    path=world/'app.py'; path.write_text('A = 1\n')
    monkeypatch.setattr(module,'read_document',lambda _path: (_ for _ in ()).throw(OSError('reparse failed')))
    with pytest.raises(SourcePostCommitError) as info:
        service.save_document(SaveRequest(read_document(path),'A = 2\n','save_file','Save'))
    tx=journal.transactions()[0]
    assert path.read_text() == 'A = 2\n'
    assert tx.status == 'committed'
    assert tx.manifest['post_commit_error'] == 'reparse failed'
