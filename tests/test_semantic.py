from pathlib import Path
from pybrowser.semantic import analyze_source
from pybrowser.semantic_queries import references_in_world
from pybrowser.project import open_world


def test_symbols_references_and_native_diagnostics():
    source = '''# category: first
# category: second
class App:
    def run(self, value):
        missing(value)

    def run(self):
        return 1
'''
    result = analyze_source(Path("app.py"), source)
    kinds = {(item.name, item.kind) for item in result.symbols}
    assert ("App", "class") in kinds
    assert ("run", "method") in kinds
    assert ("value", "parameter") in kinds
    assert any(item.name == "missing" and item.kind == "call" for item in result.references)
    rules = {item.rule for item in result.diagnostics}
    assert "duplicate-definition" in rules
    assert "duplicate-category-directive" in rules
    assert "possibly-undefined-local" in rules


def test_unused_category_metadata():
    result = analyze_source(Path("app.py"), "# category: abandoned\nprint('x')\n")
    assert any(item.rule == "unused-category-metadata" for item in result.diagnostics)


def test_general_references_resolve_containing_members(tmp_path):
    path = tmp_path / "app.py"
    path.write_text("VALUE = 1\n\ndef use():\n    return VALUE\n")
    world = open_world(tmp_path)
    semantic = analyze_source(path, path.read_text())
    results = references_in_world(world, {path.resolve(): semantic}, "VALUE")
    assert {item.reference_kind for item in results} >= {"write", "read"}
    assert any(item.label.startswith("use") for item in results)
