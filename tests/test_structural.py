from pathlib import Path
from pybrowser.model import Document
from pybrowser.parser import build_index, validate
from pybrowser.structural import add_class, add_function, add_method, convert_method_kind, delete_member, move_member


def doc(text):
    scopes = build_index(Path("x.py"), text)
    return Document(Path("x.py"), text, "utf-8", "\n", True, (0, 0, ""), scopes)


def real(scope):
    return [item for item in scope.members if not item.synthetic]


def test_add_function_class_and_method():
    first = add_function(doc("VALUE = 1\n"), "run", "Functions")
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
