from pathlib import Path
from pybrowser.model import Document
from pybrowser.parser import build_index, validate
from pybrowser.structural import add_class, add_function, add_method, convert_method_kind, delete_member, duplicate_member, move_member


def doc(text):
    scopes = build_index(Path("x.py"), text)
    return Document(Path("x.py"), text, "utf-8", "\n", True, (0, 0, ""), scopes)


def real(scope):
    return [item for item in scope.members if not item.synthetic]


def test_add_function_class_and_method():
    first = add_function(doc("VALUE = 1\n"), "run", "-- functions --")
    validate(first.text, "x.py")
    second = add_class(doc(first.text), "App", "Classes")
    validate(second.text, "x.py")
    third = add_method(doc(second.text), "App", "start", "lifecycle")
    validate(third.text, "x.py")
    assert "def start(self):" in third.text


def test_move_and_delete_member():
    source = "# category: Old\ndef run():\n    pass\n"
    document = doc(source)
    member = real(document.scopes[0])[0]
    moved = move_member(document, member, "New")
    assert "# category: New" in moved.text
    moved_doc = doc(moved.text)
    deleted = delete_member(moved_doc, real(moved_doc.scopes[0])[0])
    assert "def run" not in deleted.text


def test_convert_method_kind():
    source = "class App:\n    def run(self, value):\n        pass\n"
    document = doc(source)
    member = real(next(scope for scope in document.scopes if scope.name == "App"))[0]
    converted = convert_method_kind(document, member, "class")
    assert "@classmethod" in converted.text
    assert "def run(cls, value):" in converted.text
    validate(converted.text, "x.py")


def test_category_metadata_is_not_in_editable_entity_source():
    source = "class App:\n    # category: search\n    def focus(self):\n        pass\n"
    document = doc(source)
    scope = next(item for item in document.scopes if item.name == "App")
    member = real(scope)[0]
    assert document.source(member).startswith("    def focus")
    assert "# category:" not in document.source(member)

def test_move_replaces_existing_metadata_without_duplication():
    source = "class App:\n    # category: old\n    def focus(self):\n        pass\n"
    document = doc(source)
    scope = next(item for item in document.scopes if item.name == "App")
    moved = move_member(document, real(scope)[0], "search")
    assert moved.text.count("# category:") == 1
    assert "    # category: search\n    def focus" in moved.text
    moved_doc = doc(moved.text)
    moved_scope = next(item for item in moved_doc.scopes if item.name == "App")
    assert real(moved_scope)[0].category == "search"


def test_delete_removes_associated_category_metadata():
    source = "class App:\n    # category: search\n    def focus(self):\n        pass\n"
    document = doc(source)
    scope = next(item for item in document.scopes if item.name == "App")
    deleted = delete_member(document, real(scope)[0])
    assert "# category:" not in deleted.text
    assert "def focus" not in deleted.text

def test_move_inserts_class_indentation():
    source = "class App:\n    def focus(self):\n        pass\n"
    document = doc(source)
    scope = next(item for item in document.scopes if item.name == "App")
    moved = move_member(document, real(scope)[0], "search")
    assert "    # category: search\n    def focus" in moved.text


def test_duplicate_method_is_adjacent_and_semantically_duplicate():
    from pybrowser.semantic import analyze_source
    source = "class ActivityIndicator:\n    def start(self):\n        pass\n"
    document = doc(source)
    scope = next(item for item in document.scopes if item.name == "ActivityIndicator")
    duplicated = duplicate_member(document, real(scope)[0])
    assert duplicated.text.count("def start(self):") == 2
    assert duplicated.text.index("def start(self):") < duplicated.text.rindex("def start(self):")
    semantic = analyze_source(Path("x.py"), duplicated.text)
    assert any(item.rule == "duplicate-definition" and "start" in item.message for item in semantic.diagnostics)
