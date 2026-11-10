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
    world,journal,service,notifications=service_for(tmp_path)
    path=world/'app.py'; path.write_text('A = 1\n')
    monkeypatch.setattr(module,'read_document',lambda _path: (_ for _ in ()).throw(OSError('reparse failed')))
    result=service.save_document(SaveRequest(read_document(path),'A = 2\n','save_file','Save'))
    tx=journal.transactions()[0]
    assert path.read_text() == 'A = 2\n'
    assert result.document.text == 'A = 2\n'
    assert tx.status == 'committed'
    assert 'reparse failed' in tx.manifest['post_commit_error']

def test_notification_failure_returns_committed_result_warning(tmp_path):
    world = tmp_path / 'world'; world.mkdir(); path = world / 'app.py'; path.write_text('A = 1\n')
    journal = RecoveryJournal(world, tmp_path / 'history')
    def broken_notify(_path, _origin): raise RuntimeError('notify failed')
    result = SourceWriteService(journal, broken_notify).save_document(
        SaveRequest(read_document(path), 'A = 2\n', 'save_file', 'Save'))
    assert result.document.text == 'A = 2\n'
    assert result.warnings == ('Workspace notification failed: notify failed',)
    assert result.transaction.status == 'committed'

def test_retention_failure_is_warning_after_committed_save(tmp_path, monkeypatch):
    world,journal,service,notifications=service_for(tmp_path)
    path=world/'app.py'; path.write_text('A = 1\n')
    monkeypatch.setattr(journal,'prune',lambda: (_ for _ in ()).throw(OSError('prune failed')))
    result=service.save_document(SaveRequest(read_document(path),'A = 2\n','save_file','Save'))
    assert result.transaction.status == 'committed'
    assert path.read_text() == 'A = 2\n'
    assert any('Recovery retention cleanup failed' in warning for warning in result.warnings)


def test_reparse_failure_returns_fallback_committed_document(tmp_path, monkeypatch):
    import pybrowser.source_write_service as module
    world,journal,service,notifications=service_for(tmp_path)
    path=world/'app.py'; path.write_text('A = 1\n')
    monkeypatch.setattr(module,'read_document',lambda _path: (_ for _ in ()).throw(OSError('reparse failed')))
    result=service.save_document(SaveRequest(read_document(path),'A = 2\n','save_file','Save'))
    assert result.document.text == 'A = 2\n'
    assert result.document.signature[2]
    assert result.document.scopes == ()
    assert result.transaction.status == 'committed'
    assert any('Reparse failed after commit' in warning for warning in result.warnings)

def test_stable_read_conflict_uses_same_bytes_for_check_and_journal(tmp_path, monkeypatch):
    import pybrowser.source_write_service as module
    from pybrowser.saving import StableFileRead
    world,journal,service,notifications=service_for(tmp_path)
    path=world/'app.py'; path.write_text('A = 1\n'); document=read_document(path)
    path.write_text('A = 9\n')
    actual=module.stable_read(path)
    monkeypatch.setattr(module,'stable_read',lambda _path: actual)
    with pytest.raises(SourceConflictError): service.save_document(SaveRequest(document,'A = 2\n','save_file','save'))
    assert path.read_text() == 'A = 9\n' and journal.transactions() == ()


def test_create_file_never_replaces_concurrently_created_target(tmp_path, monkeypatch):
    world,journal,service,notifications=service_for(tmp_path)
    path=world/'pkg'/'__init__.py'
    original=service._create_bytes_exclusive
    def race(target,data,mode):
        target.parent.mkdir(parents=True,exist_ok=True); target.write_text('EXTERNAL = 1\n')
        return original(target,data,mode)
    monkeypatch.setattr(service,'_create_bytes_exclusive',race)
    with pytest.raises(SourceConflictError): service.create_file(path,b'VALUE = 2\n')
    assert path.read_text() == 'EXTERNAL = 1\n'
    assert journal.transactions()[0].status == 'failed'

def test_final_signature_check_refuses_change_during_preparation(tmp_path, monkeypatch):
    import pybrowser.source_write_service as module
    world,journal,service,notifications=service_for(tmp_path)
    path=world/'app.py'; path.write_text('A = 1\n'); document=read_document(path)
    original=service._replace_bytes
    def changed_before_replace(target,data,mode,expected):
        target.write_text('EXTERNAL = 9\n')
        return original(target,data,mode,expected)
    monkeypatch.setattr(service,'_replace_bytes',changed_before_replace)
    with pytest.raises(SourceConflictError): service.save_document(SaveRequest(document,'A = 2\n','save_file','save'))
    assert path.read_text() == 'EXTERNAL = 9\n'
    assert journal.transactions()[0].status == 'failed'


def test_cooperative_path_lock_rejects_second_writer(tmp_path):
    world,journal,service,notifications=service_for(tmp_path)
    path=world/'app.py'; path.write_text('A = 1\n')
    with journal.locks.acquire(path):
        with pytest.raises(SourceConflictError):
            service.save_document(SaveRequest(read_document(path), 'A = 2\n', 'save_file', 'save'))
    assert journal.transactions() == ()
