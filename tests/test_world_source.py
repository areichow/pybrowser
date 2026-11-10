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


def test_repeated_overlay_stage_preserves_disk_baseline_and_rejects_stale_editor(tmp_path):
    from pybrowser.world_source import OverlayConflictError
    from pybrowser.saving import stable_read
    path = tmp_path / "app.py"
    path.write_bytes(b"A = 1\n")
    disk_signature = stable_read(path).signature
    store = WorldSourceStore(tmp_path)
    first = store.stage_bytes(path, b"A = 2\n", expected_visible_signature=disk_signature)
    first_document = store.read_document(path)
    assert first_document.signature == first.signature
    assert first_document.disk_signature == disk_signature
    second = store.stage_bytes(path, b"A = 3\n", expected_visible_signature=first_document.signature)
    assert second.disk_signature == disk_signature
    assert store.read_document(path).text == "A = 3\n"
    with __import__('pytest').raises(OverlayConflictError):
        store.stage_bytes(path, b"A = 4\n", expected_visible_signature=first_document.signature)
    assert path.read_bytes() == b"A = 1\n"


def test_external_disk_change_does_not_destroy_overlay_baseline(tmp_path):
    from pybrowser.saving import stable_read
    path = tmp_path / "app.py"
    path.write_bytes(b"A = 1\n")
    baseline = stable_read(path).signature
    store = WorldSourceStore(tmp_path)
    store.stage_bytes(path, b"A = 2\n", expected_visible_signature=baseline)
    document = store.read_document(path)
    path.write_bytes(b"EXTERNAL = 9\n")
    store.stage_bytes(path, b"A = 3\n", expected_visible_signature=document.signature)
    assert store.read_document(path).disk_signature == baseline
    assert store.read_document(path).text == "A = 3\n"


def test_virtual_python_file_is_in_effective_world_and_disappears_on_discard(tmp_path):
    from pybrowser.code_queries import implementers
    from pybrowser.project import open_world
    existing = tmp_path / "existing.py"
    existing.write_bytes(b"VALUE = 1\n")
    virtual = tmp_path / "pkg" / "new_module.py"
    store = WorldSourceStore(tmp_path)
    store.stage_bytes(virtual, b"def virtual_method():\n    return 'needle'\n")
    world = open_world(tmp_path)
    effective = type(world)(world.root, store.effective_modules(world.modules), world.single_file)
    assert virtual.resolve() in {entry.path.resolve() for entry in effective.modules}
    assert implementers(effective, "virtual_method", source_map=store.source_map())
    store.discard(virtual)
    assert virtual.resolve() not in {entry.path.resolve() for entry in store.effective_modules(world.modules)}
