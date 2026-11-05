from pathlib import Path
from pybrowser.model import Kind
from pybrowser.parser import build_index

SOURCE = '''\"\"\"Example module.\"\"\"
import os

CONSTANT = 1
value = 2
__all__ = ["Outer"]

class Outer:
    \"\"\"Outer documentation.\"\"\"
    class_value = 3

    @property
    def name(self):
        return "name"

    @name.setter
    def name(self, value):
        pass

    @staticmethod
    def make():
        return Outer()

    class Inner:
        async def work(self):
            pass

if enabled:
    run()
for item in items:
    visit(item)
while ready:
    tick()
with open("x") as stream:
    stream.read()
try:
    risky()
except OSError:
    pass
match command:
    case "go":
        run()
'''

def real(scope):
    return [m for m in scope.members if not m.synthetic]

def test_complete_module_classification():
    scopes = build_index(Path("example.py"), SOURCE)
    module = scopes[0]
    categories = {m.category for m in real(module)}
    assert {"Documentation", "Imports", "Constants", "Variables", "Module Metadata", "Executable Code"} <= categories
    kinds = {m.kind for m in real(module)}
    assert {Kind.IF, Kind.FOR, Kind.WHILE, Kind.WITH, Kind.TRY, Kind.MATCH} <= kinds

def test_nested_classes_and_decorator_labels():
    scopes = build_index(Path("example.py"), SOURCE)
    assert [s.name for s in scopes] == ["<module>", "Outer.Inner", "Outer"]
    outer = scopes[-1]
    labels = [m.label for m in real(outer)]
    assert any("[property]" in label for label in labels)
    assert any("[setter]" in label for label in labels)
    assert any("[staticmethod]" in label for label in labels)
    assert any(m.category == "Class Variables" for m in real(outer))

def test_category_level_member_for_contiguous_run():
    source = "# category: Config\nA = 1\n# category: Config\nB = 2\n"
    scope = build_index(Path("example.py"), source)[0]
    assert scope.members[0].label == "<entire category>"
    assert scope.members[0].synthetic
    assert scope.members[0].span.start == source.index("A = 1")
    assert scope.members[0].span.end == len(source)

def test_every_direct_statement_appears_once_excluding_synthetic():
    scopes = build_index(Path("example.py"), SOURCE)
    module = real(scopes[0])
    # docstring, import, three assignments, six executable compounds
    assert len(module) == 11
