from pybrowser.index_cache import ModuleIndexCache


def test_cache_invalidates_after_file_change(tmp_path):
    path = tmp_path / "app.py"
    path.write_text("A = 1\n")
    cache = ModuleIndexCache()
    cache.put(path, ())
    assert cache.get(path) is not None
    path.write_text("A = 200\n")
    assert cache.get(path) is None


def test_cache_retain_removes_deleted_world_members(tmp_path):
    one = tmp_path / "one.py"
    two = tmp_path / "two.py"
    one.write_text("A=1\n")
    two.write_text("B=2\n")
    cache = ModuleIndexCache()
    cache.put(one, ())
    cache.put(two, ())
    cache.retain({one})
    assert cache.get(one) is not None
    assert cache.get(two) is None


def test_explicit_invalidate_removes_cached_module(tmp_path):
    path = tmp_path / "new_class.py"
    path.write_text("class NewClass:\n    pass\n")
    cache = ModuleIndexCache()
    cache.put(path, ())
    assert cache.get(path) is not None
    cache.invalidate(path)
    assert cache.get(path) is None
