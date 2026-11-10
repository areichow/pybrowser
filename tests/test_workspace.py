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
