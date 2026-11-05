from pybrowser.index_worker import index_module


def test_process_safe_index_worker_returns_semantics(tmp_path):
    path = tmp_path / "app.py"
    path.write_text("class App:\n    def run(self):\n        return missing\n")
    result_path, scopes, semantic, error = index_module(str(path))
    assert result_path == path
    assert error is None
    assert any(scope.name == "App" for scope in scopes)
    assert any(item.rule == "possibly-undefined-local" for item in semantic.diagnostics)


def test_process_safe_index_worker_returns_parse_error(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text("def broken(:\n")
    _path, scopes, semantic, error = index_module(str(path))
    assert scopes is None
    assert semantic is None
    assert error
