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
    first = Workspace(); first.set_world(world); first.set_write_mode(WriteMode.MANUAL_COMMIT)
    result = first.write_service.save_document(SaveRequest(first.read_document(path), "A = 2\n", "save_file", "stage"))
    assert path.read_bytes() == b"A = 1\n"
    second = Workspace(); second.set_world(world)
    assert second.read_document(path).text == "A = 2\n"
    assert second.staged_paths() == (path.resolve(),)
