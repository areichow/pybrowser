from pybrowser.code_queries import implementers
from pybrowser.index_worker import index_module
from pybrowser.navigation import search_file
from pybrowser.project import open_world
from pybrowser.world_source import WorldSourceStore


def test_overlay_source_precedes_disk_for_documents_and_queries(tmp_path):
    path = tmp_path / "app.py"
    path.write_bytes(b"def disk_name():\n    return 'disk'\n")
    store = WorldSourceStore(tmp_path)
    staged = b"def staged_name():\n    return 'overlay needle'\n"
    store.stage_bytes(path, staged)
    assert store.read_document(path).text == staged.decode()
    assert path.read_bytes() != staged
    source_map = store.source_map()
    world = open_world(tmp_path)
    assert implementers(world, "staged_name", source_map=source_map)
    assert search_file(path, "app", "overlay needle", source_map)
    _path, scopes, semantic, error = index_module(str(path), staged)
    assert error is None and scopes and semantic is not None


def test_overlay_supports_virtual_new_file_and_discard(tmp_path):
    path = tmp_path / "new.py"
    store = WorldSourceStore(tmp_path)
    store.stage_bytes(path, b"VALUE = 1\n")
    assert store.exists(path) and not path.exists()
    assert store.read_document(path).text == "VALUE = 1\n"
    assert store.staged_paths() == (path.resolve(),)
    store.discard(path)
    assert not store.exists(path)
