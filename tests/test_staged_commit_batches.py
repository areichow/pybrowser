from pybrowser.parser import read_document
from pybrowser.recovery import RecoveryJournal
from pybrowser.source_write_service import SaveRequest, SourceWriteService, WriteMode
from pybrowser.world_source import WorldSourceStore


def setup_staged(tmp_path, names=("a.py", "b.py")):
    world = tmp_path / "world"; world.mkdir()
    journal = RecoveryJournal(world, tmp_path / "history")
    store = WorldSourceStore(world, journal.locks)
    service = SourceWriteService(journal, source_store=store, write_mode=WriteMode.MANUAL_COMMIT)
    paths=[]; transactions=[]
    for index, name in enumerate(names, 1):
        path=world/name; path.write_bytes(f"VALUE = {index}\n".encode())
        result=service.save_document(SaveRequest(read_document(path), f"VALUE = {index+10}\n", "save_file", name))
        paths.append(path); transactions.append(result.transaction)
    return journal,store,service,paths,transactions


def prepare_batch(journal, transactions):
    batch=journal.prepare_staged_commit_batch(transactions)
    return journal.set_staged_batch_status(batch.batch_id,"committing",expected={"prepared"})


def test_schema_7_and_batch_progress(tmp_path):
    journal,store,service,paths,transactions=setup_staged(tmp_path)
    batch=prepare_batch(journal,transactions)
    assert [item.progress for item in batch.files] == ["pending","pending"]
    batch=journal.set_staged_file_progress(batch.batch_id,0,"replacing",expected="pending")
    batch=journal.set_staged_file_progress(batch.batch_id,0,"replaced",expected="replacing")
    assert [item.progress for item in batch.files] == ["replaced","pending"]
    assert journal.incomplete_staged_commit_batches()[0].batch_id == batch.batch_id


def test_all_after_restart_finalizes_batch(tmp_path):
    journal,store,service,paths,transactions=setup_staged(tmp_path)
    batch=prepare_batch(journal,transactions)
    for item,path,tx in zip(batch.files,paths,transactions):
        path.write_bytes(journal.snapshot_path(tx,"after").read_bytes())
    reopened=RecoveryJournal(journal.world_root,tmp_path/"history")
    found=reopened.incomplete_staged_commit_batches()[0]
    assert {state for _path,state in reopened.inspect_staged_commit_batch(found)} == {"current equals after"}
    result=reopened.resolve_staged_commit_batch(found,"forward")
    assert result.transactions
    assert reopened.incomplete_staged_commit_batches()==()
    assert reopened.active_overlays()==()


def test_mixed_batch_can_roll_back_or_complete_forward(tmp_path):
    journal,store,service,paths,transactions=setup_staged(tmp_path)
    batch=prepare_batch(journal,transactions)
    paths[0].write_bytes(journal.snapshot_path(transactions[0],"after").read_bytes())
    states={state for _path,state in journal.inspect_staged_commit_batch(batch)}
    assert states == {"current equals before","current equals after"}
    journal.resolve_staged_commit_batch(batch,"rollback")
    assert paths[0].read_bytes()==journal.snapshot_path(transactions[0],"before").read_bytes()
    assert paths[1].read_bytes()==journal.snapshot_path(transactions[1],"before").read_bytes()
    assert journal.active_overlays()

    # A fresh journal/world proves complete-forward from the same mixed shape.
    other=tmp_path/"other"; other.mkdir()
    journal2=RecoveryJournal(other,tmp_path/"history2"); store2=WorldSourceStore(other,journal2.locks)
    service2=SourceWriteService(journal2,source_store=store2,write_mode=WriteMode.MANUAL_COMMIT)
    txs=[]; ps=[]
    for i,name in enumerate(("a.py","b.py"),1):
        path=other/name; path.write_bytes(f"X = {i}\n".encode()); ps.append(path)
        txs.append(service2.save_document(SaveRequest(read_document(path),f"X = {i+5}\n","save_file",name)).transaction)
    batch2=prepare_batch(journal2,txs); ps[0].write_bytes(journal2.snapshot_path(txs[0],"after").read_bytes())
    journal2.resolve_staged_commit_batch(batch2,"forward")
    assert all(path.read_bytes()==journal2.snapshot_path(tx,"after").read_bytes() for path,tx in zip(ps,txs))
    assert journal2.active_overlays()==()


def test_foreign_state_allows_manual_review_only(tmp_path):
    import pytest
    from pybrowser.recovery import RecoveryConflictError
    journal,store,service,paths,transactions=setup_staged(tmp_path)
    batch=prepare_batch(journal,transactions)
    paths[0].write_bytes(b"FOREIGN = 99\n")
    assert "current differs from both" in {state for _path,state in journal.inspect_staged_commit_batch(batch)}
    with pytest.raises(RecoveryConflictError): journal.resolve_staged_commit_batch(batch,"forward")
    with pytest.raises(RecoveryConflictError): journal.resolve_staged_commit_batch(batch,"rollback")
    reviewed=journal.resolve_staged_commit_batch(batch,"review")
    assert reviewed.status == "reviewed"
    assert journal.active_overlays()


def test_virtual_file_after_state_finalizes(tmp_path):
    world=tmp_path/"world"; world.mkdir(); journal=RecoveryJournal(world,tmp_path/"history")
    store=WorldSourceStore(world,journal.locks); service=SourceWriteService(journal,source_store=store,write_mode=WriteMode.MANUAL_COMMIT)
    path=world/"new.py"; tx=service.create_file(path,b"VALUE = 1\n").transaction
    batch=prepare_batch(journal,(tx,)); path.write_bytes(journal.snapshot_path(tx,"after").read_bytes())
    assert journal.inspect_staged_commit_batch(batch)[0][1] == "current equals after"
    journal.resolve_staged_commit_batch(batch,"forward")
    assert journal.active_overlays()==()


def test_staged_write_mirror_failure_still_publishes_overlay(tmp_path,monkeypatch):
    import pybrowser.recovery as recovery
    world=tmp_path/"world"; world.mkdir(); path=world/"app.py"; path.write_bytes(b"A = 1\n")
    journal=RecoveryJournal(world,tmp_path/"history"); store=WorldSourceStore(world,journal.locks)
    service=SourceWriteService(journal,source_store=store,write_mode=WriteMode.MANUAL_COMMIT)
    original=recovery._json_write
    def fail(target,value):
        if target.name=="manifest.json": raise OSError("mirror failed")
        return original(target,value)
    monkeypatch.setattr(recovery,"_json_write",fail)
    result=service.save_document(SaveRequest(read_document(path),"A = 2\n","save_file","stage"))
    assert store.read_document(path).text=="A = 2\n"
    assert journal.active_overlays()
    assert any("Portable manifest repair failed" in warning for warning in result.warnings)


def test_incomplete_batch_blocks_discard_and_new_commit(tmp_path):
    import pytest
    from pybrowser.source_write_service import SourceConflictError
    journal,store,service,paths,transactions=setup_staged(tmp_path)
    prepare_batch(journal,transactions)
    with pytest.raises(SourceConflictError): service.discard_staged(paths[0])
    with pytest.raises(SourceConflictError): service.commit_all_staged()
    assert len(journal.active_overlays())==2


def test_normal_commit_selected_uses_completed_one_file_batch(tmp_path):
    journal,store,service,paths,transactions=setup_staged(tmp_path,names=("a.py",))
    result=service.commit_staged(paths[0])
    batch_id=None
    with journal._connect() as db:
        row=db.execute("SELECT batch_id,status FROM staged_commit_batches").fetchone()
        batch_id=row["batch_id"]
        assert row["status"]=="completed"
        progress=db.execute("SELECT progress FROM staged_commit_files WHERE batch_id=?",(batch_id,)).fetchone()[0]
        assert progress=="replaced"
    assert result.transaction.manifest["committed_to_disk"] is True
    assert journal.get_staged_commit_batch(batch_id).recovered_at is None
