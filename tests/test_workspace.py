import pytest
pytest.importorskip("PySide6")
from pybrowser.project import open_world
from pybrowser.workspace import Workspace


def test_workspace_tracks_shared_world_and_windows(tmp_path):
    path = tmp_path / "app.py"
    path.write_bytes(b"VALUE = 1\n")
    world = open_world(path)
    workspace = Workspace()
    workspace.set_world(world)
    assert workspace.world is world
    assert workspace.journal.world_root == world.root
    assert workspace.write_service.locks is workspace.journal.locks


def test_workspace_restores_durable_overlay_after_restart(tmp_path):
    from pybrowser.source_write_service import SaveRequest, WriteMode
    path = tmp_path / "app.py"; path.write_bytes(b"A = 1\n")
    world = open_world(path)
    from PySide6.QtCore import QSettings
    settings = QSettings("PyBrowser", "PyBrowser")
    previous = settings.value("source/writeMode", None)
    try:
        first = Workspace(); first.set_world(world); first.set_write_mode(WriteMode.MANUAL_COMMIT)
        first.write_service.save_document(SaveRequest(first.read_document(path), "A = 2\n", "save_file", "stage"))
        assert path.read_bytes() == b"A = 1\n"
        second = Workspace(); second.set_world(world)
        assert second.read_document(path).text == "A = 2\n"
        assert second.staged_paths() == (path.resolve(),)
    finally:
        if previous is None: settings.remove("source/writeMode")
        else: settings.setValue("source/writeMode", previous)
        settings.sync()


def test_overlay_notifications_publish_content_change_without_world_rebuild(tmp_path):
    from pybrowser.source_write_service import SaveRequest, WriteMode
    path = tmp_path / "app.py"; path.write_bytes(b"A = 1\n")
    world = open_world(path)
    workspace = Workspace(); workspace.set_world(world); workspace.set_write_mode(WriteMode.MANUAL_COMMIT)
    file_events = []; world_events = []; module_events = []
    workspace.file_changed.connect(lambda changed, origin: file_events.append((changed, origin)))
    workspace.world_changed.connect(lambda current: world_events.append(current))
    workspace.module_set_changed.connect(lambda current: module_events.append(current))
    origin = object()
    workspace.write_service.save_document(SaveRequest(workspace.read_document(path), "A = 2\n", "save_file", "stage", origin=origin))
    assert file_events == [(path.resolve(), origin)]
    assert world_events == []
    assert module_events == []


def test_staged_commit_and_abandon_block_unsaved_affected_windows(tmp_path, monkeypatch):
    from pybrowser.workspace import WorkspaceStagingError
    path = tmp_path / "app.py"; path.write_bytes(b"A = 1\n")
    workspace = Workspace(); workspace.set_world(open_world(path))
    class Blocker:
        def windowTitle(self): return "Unsaved File View[*]"
    blocker = Blocker()
    monkeypatch.setattr(workspace, "unsaved_windows_for", lambda paths: (blocker,))
    monkeypatch.setattr(workspace, "activate_window", lambda window: None)
    with pytest.raises(WorkspaceStagingError): workspace.commit_staged_path(path)
    with pytest.raises(WorkspaceStagingError): workspace.discard_staged_path(path)


def test_virtual_overlay_publishes_module_set_change(tmp_path):
    from pybrowser.source_write_service import WriteMode
    world = open_world(tmp_path)
    workspace = Workspace(); workspace.set_world(world); workspace.set_write_mode(WriteMode.MANUAL_COMMIT)
    events = []
    workspace.module_set_changed.connect(events.append)
    path = tmp_path / "virtual.py"
    workspace.write_service.create_file(path, b"VALUE = 1\n")
    assert len(events) == 1
    assert path.resolve() in {entry.path.resolve() for entry in events[0].modules}


def test_existing_module_notification_does_not_rebuild_effective_world(tmp_path, monkeypatch):
    path = tmp_path / "app.py"; path.write_bytes(b"A = 1\n")
    workspace = Workspace(); workspace.set_world(open_world(tmp_path))
    monkeypatch.setattr(workspace, "effective_world", lambda: (_ for _ in ()).throw(
        AssertionError("existing content change rebuilt effective World")))
    events = []
    workspace.file_changed.connect(lambda changed, origin: events.append((changed, origin)))
    origin = object()
    workspace.announce_file_changed(path, origin)
    assert events == [(path.resolve(), origin)]


def test_discarded_virtual_module_still_publishes_membership_change(tmp_path):
    from pybrowser.source_write_service import WriteMode
    workspace = Workspace(); workspace.set_world(open_world(tmp_path))
    workspace.set_write_mode(WriteMode.MANUAL_COMMIT)
    path = tmp_path / "virtual.py"
    workspace.write_service.create_file(path, b"VALUE = 1\n")
    events = []
    workspace.module_set_changed.connect(events.append)
    workspace.write_service.discard_staged(path)
    assert len(events) == 1
    assert path.resolve() not in {item.path.resolve() for item in events[0].modules}
