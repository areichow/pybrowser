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


def test_lambda_parameter_is_defined_in_lambda_scope():
    source = """def mapping_hint(value):
    normalize = lambda path: path.strip()
    return normalize(value)
"""
    result = analyze_source(Path("app.py"), source)
    undefined = {item.message for item in result.diagnostics if item.rule == "possibly-undefined-local"}
    assert not any("'path'" in message for message in undefined)
    assert any(item.name == "path" and item.kind == "parameter" for item in result.symbols)


def test_except_alias_is_defined_in_handler_scope():
    source = """def worker():
    try:
        run()
    except Exception as error:
        print(error)
"""
    result = analyze_source(Path("app.py"), source)
    undefined = {item.message for item in result.diagnostics if item.rule == "possibly-undefined-local"}
    assert not any("'error'" in message for message in undefined)
    assert any(item.name == "error" and item.kind == "exception" for item in result.symbols)
    assert any(item.name == "error" and item.kind == "write" for item in result.references)


def test_lambda_body_still_reports_truly_missing_name():
    source = """def outer():
    callback = lambda item: missing(item)
    return callback
"""
    result = analyze_source(Path("app.py"), source)
    undefined = {item.message for item in result.diagnostics if item.rule == "possibly-undefined-local"}
    assert any("'missing'" in message for message in undefined)
    assert not any("'item'" in message for message in undefined)


def test_module_class_defined_later_is_known_global():
    source = """class Repository:
    def lock(self):
        return RepoLock(self)

class RepoLock:
    pass
"""
    result = analyze_source(Path("repo.py"), source)
    assert not any(item.rule == "possibly-undefined-local" and "RepoLock" in item.message for item in result.diagnostics)


def test_module_functions_defined_later_are_known_globals():
    source = """def run():
    diagnostic('ready')

def diagnostic(message):
    return colorize(message)

def colorize(value):
    return value
"""
    result = analyze_source(Path("app.py"), source)
    messages = [item.message for item in result.diagnostics if item.rule == "possibly-undefined-local"]
    assert not any("diagnostic" in message for message in messages)
    assert not any("colorize" in message for message in messages)


def test_implicit_module_globals_are_not_undefined():
    source = """def paths():
    return (__file__, __name__, __package__, __loader__, __spec__, __cached__, __builtins__, __annotations__, __doc__, __debug__)
"""
    result = analyze_source(Path("app.py"), source)
    messages = [item.message for item in result.diagnostics if item.rule == "possibly-undefined-local"]
    for name in ("__file__", "__name__", "__package__", "__loader__", "__spec__", "__cached__", "__builtins__", "__annotations__", "__doc__", "__debug__"):
        assert not any(repr(name) in message for message in messages)


def test_arbitrary_dunder_is_not_assumed_to_be_a_bare_global():
    result = analyze_source(Path("app.py"), "def run():\n    return __totally_custom_dunder__\n")
    assert any(item.rule == "possibly-undefined-local" and "__totally_custom_dunder__" in item.message for item in result.diagnostics)


def test_special_method_definition_does_not_need_global_whitelisting():
    result = analyze_source(Path("app.py"), "class Value:\n    def __repr__(self):\n        return 'Value()'\n")
    assert not any(item.rule == "possibly-undefined-local" and "__repr__" in item.message for item in result.diagnostics)
