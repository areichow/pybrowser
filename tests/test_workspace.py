import pytest
pytest.importorskip("PySide6")
from pathlib import Path
from pybrowser.workspace import Workspace


def test_workspace_tracks_shared_world_and_windows():
    workspace = Workspace()
    sentinel = object()
    workspace.set_world(sentinel)
    assert workspace.world is sentinel
