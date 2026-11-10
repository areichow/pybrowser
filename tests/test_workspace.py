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


def test_overlay_notifications_publish_effective_world_once(tmp_path):
    from pybrowser.source_write_service import SaveRequest, WriteMode
    path = tmp_path / "app.py"; path.write_bytes(b"A = 1\n")
    world = open_world(path)
    workspace = Workspace(); workspace.set_world(world); workspace.set_write_mode(WriteMode.MANUAL_COMMIT)
    file_events = []; world_events = []
    workspace.file_changed.connect(lambda changed, origin: file_events.append((changed, origin)))
    workspace.world_changed.connect(lambda current: world_events.append(current))
    origin = object()
    workspace.write_service.save_document(SaveRequest(workspace.read_document(path), "A = 2\n", "save_file", "stage", origin=origin))
    assert file_events == [(path.resolve(), origin)]
    assert len(world_events) == 1
    assert world_events[0].modules[0].path == path.resolve()


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
