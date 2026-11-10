import pytest
from pybrowser.parser import read_document
from pybrowser.project import open_world
from pybrowser.recovery import RecoveryJournal
from pybrowser.source_write_service import SaveRequest, SourceConflictError, SourceWriteService, WriteMode
from pybrowser.world_source import WorldSourceStore


def staging_service(world, history):
    journal = RecoveryJournal(world, history)
    store = WorldSourceStore(world, journal.locks)
    return journal, store, SourceWriteService(journal, source_store=store, write_mode=WriteMode.MANUAL_COMMIT)


def test_existing_file_stage_restart_and_commit(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_bytes(b'A = 1\n')
    history=tmp_path/'history'; journal,store,service=staging_service(world,history)
    result=service.save_document(SaveRequest(read_document(path),'A = 2\n','save_file','stage'))
    assert path.read_bytes()==b'A = 1\n' and result.document.text=='A = 2\n'
    reopened=RecoveryJournal(world,history); active=reopened.active_overlays(); assert len(active)==1
    restored=WorldSourceStore(world,reopened.locks)
    active_path,tx,signature=active[0]; data=reopened.snapshot_path(tx,'after').read_bytes()
    restored.stage_bytes(active_path,data,disk_signature=signature,transaction_id=tx.transaction_id,restoring=True)
    assert restored.read_document(path).text=='A = 2\n'
    committed=SourceWriteService(reopened,source_store=restored).commit_staged(path)
    assert path.read_bytes()==b'A = 2\n' and reopened.active_overlays()==()
    assert committed.transaction.manifest['committed_to_disk'] is True


def test_repeated_stage_keeps_original_before_and_external_conflict(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_bytes(b'A = 1\n')
    journal,store,service=staging_service(world,tmp_path/'history')
    first=service.save_document(SaveRequest(read_document(path),'A = 2\n','save_file','one'))
    second=service.save_document(SaveRequest(first.document,'A = 3\n','save_file','two'))
    assert journal.snapshot_path(second.transaction,'before').read_bytes()==b'A = 1\n'
    path.write_bytes(b'EXTERNAL = 9\n')
    with pytest.raises(SourceConflictError): SourceWriteService(journal,source_store=store).commit_staged(path)
    assert path.read_bytes()==b'EXTERNAL = 9\n' and store.read_document(path).text=='A = 3\n'


def test_virtual_file_stage_collision_discard_and_commit(tmp_path):
    world=tmp_path/'world'; world.mkdir(); journal,store,service=staging_service(world,tmp_path/'history')
    path=world/'new.py'
    staged=service.create_file(path,b'VALUE = 1\n')
    assert not path.exists() and store.read_document(path).text=='VALUE = 1\n'
    path.write_bytes(b'EXTERNAL = 2\n')
    with pytest.raises(SourceConflictError): SourceWriteService(journal,source_store=store).commit_staged(path)
    service.discard_staged(path); assert store.staged_paths()==() and path.read_bytes()==b'EXTERNAL = 2\n'


def test_active_overlay_is_retention_protected(tmp_path):
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_bytes(b'A = 0\n')
    journal=RecoveryJournal(world,tmp_path/'history',max_transactions=1,min_days=0,max_megabytes=1)
    store=WorldSourceStore(world,journal.locks)
    service=SourceWriteService(journal,source_store=store,write_mode=WriteMode.MANUAL_COMMIT)
    staged=service.save_document(SaveRequest(read_document(path),'A = 9\n','save_file','stage')).transaction
    journal.prune()
    assert journal.get(staged.transaction_id) is not None and journal.active_overlays()


def test_commit_all_is_atomic_when_later_path_conflicts(tmp_path):
    world=tmp_path/'world'; world.mkdir(); first=world/'a.py'; second=world/'b.py'
    first.write_bytes(b'A = 1\n'); second.write_bytes(b'B = 1\n')
    journal,store,service=staging_service(world,tmp_path/'history')
    service.save_document(SaveRequest(read_document(first),'A = 2\n','save_file','a'))
    service.save_document(SaveRequest(read_document(second),'B = 2\n','save_file','b'))
    second.write_bytes(b'EXTERNAL = 9\n')
    with pytest.raises(SourceConflictError): service.commit_all_staged()
    assert first.read_bytes()==b'A = 1\n' and second.read_bytes()==b'EXTERNAL = 9\n'
    assert len(store.staged_paths())==2 and len(journal.active_overlays())==2


def test_selected_commit_manifest_failure_is_warning_after_authority(tmp_path, monkeypatch):
    import pybrowser.recovery as recovery
    world=tmp_path/'world'; world.mkdir(); path=world/'app.py'; path.write_bytes(b'A = 1\n')
    journal,store,service=staging_service(world,tmp_path/'history')
    staged=service.save_document(SaveRequest(read_document(path),'A = 2\n','save_file','stage'))
    original=recovery._json_write
    def fail_manifest(target, value):
        if target == staged.transaction.directory/'manifest.json':
            raise OSError('mirror failed')
        return original(target,value)
    monkeypatch.setattr(recovery,'_json_write',fail_manifest)
    result=SourceWriteService(journal,source_store=store).commit_staged(path)
    assert path.read_bytes()==b'A = 2\n'
    assert journal.active_overlays()==() and store.staged_paths()==()
    assert journal.get(staged.transaction.transaction_id).manifest['committed_to_disk'] is True
    assert result.warnings and 'Portable manifest repair failed' in result.warnings[0]


def test_commit_all_notification_failure_does_not_roll_back_disk(tmp_path):
    world=tmp_path/'world'; world.mkdir(); first=world/'a.py'; second=world/'b.py'
    first.write_bytes(b'A = 1\n'); second.write_bytes(b'B = 1\n')
    journal,store,service=staging_service(world,tmp_path/'history')
    service.save_document(SaveRequest(read_document(first),'A = 2\n','save_file','a'))
    service.save_document(SaveRequest(read_document(second),'B = 2\n','save_file','b'))
    journal.on_change=lambda: (_ for _ in ()).throw(RuntimeError('notify failed'))
    results=service.commit_all_staged()
    assert first.read_bytes()==b'A = 2\n' and second.read_bytes()==b'B = 2\n'
    assert journal.active_overlays()==() and store.staged_paths()==()
    assert all(any('History notification failed' in warning for warning in result.warnings)
               for result in results)
