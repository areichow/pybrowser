from pathlib import Path

from pybrowser.member_projection import project_member, project_source, restore_member
from pybrowser.model import Document
from pybrowser.parser import build_index, replacement, validate


def document(text, newline="\n"):
    scopes = build_index(Path("app.py"), text)
    return Document(Path("app.py"), text, "utf-8", newline, text.endswith(("\n", "\r")), (0, 0, ""), scopes)


def member_for(text, scope_name):
    doc = document(text, "\r\n" if "\r\n" in text else "\n")
    scope = next(scope for scope in doc.scopes if scope.name == scope_name)
    return doc, next(member for member in scope.members if not member.synthetic)


def test_class_method_projects_to_column_zero_and_round_trips():
    text = "class App:\n    def run(self):\n        if ready:\n            return 1\n"
    doc, member = member_for(text, "App")
    projection = project_member(doc, member)
    assert projection.prefix == "    "
    assert projection.text == "def run(self):\n    if ready:\n        return 1\n"
    assert restore_member(projection, projection.text) == doc.source(member)


def test_nested_decorated_async_method_round_trips():
    text = "class Outer:\n    class Inner:\n        @classmethod\n        async def run(cls):\n            return cls()\n"
    doc, member = member_for(text, "Outer.Inner")
    projection = project_member(doc, member)
    assert projection.prefix == "        "
    assert projection.text.startswith("@classmethod\nasync def run")
    assert restore_member(projection, projection.text) == doc.source(member)


def test_tab_indentation_round_trips_exactly():
    source = "\tdef run(self):\n\t\treturn 1\n"
    projection = project_source(source)
    assert projection.prefix == "\t"
    assert projection.text == "def run(self):\n\treturn 1\n"
    assert restore_member(projection, projection.text) == source


def test_blank_lines_do_not_gain_trailing_whitespace():
    source = "    def run(self):\n\n        return 1\n"
    projection = project_source(source)
    restored = restore_member(projection, projection.text)
    assert "\n    \n" not in restored
    assert restored == source


def test_edits_reindent_and_validate_in_complete_module():
    text = "class App:\n    def run(self):\n        return 1\n"
    doc, member = member_for(text, "App")
    projection = project_member(doc, member)
    edited = "def run(self):\n    value = 2\n    return value\n"
    candidate = replacement(doc, member, restore_member(projection, edited))
    validate(candidate, "app.py")
    assert "    def run(self):\n        value = 2\n        return value\n" in candidate


def test_crlf_projection_round_trip():
    source = "    def run(self):\r\n        return 1\r\n"
    projection = project_source(source)
    assert "\r\n" in projection.text
    assert restore_member(projection, projection.text) == source


def test_unsafe_mixed_prefix_falls_back_to_literal_source():
    source = "    def run(self):\n\treturn 1\n"
    projection = project_source(source)
    assert not projection.projected
    assert projection.text == source
    assert restore_member(projection, projection.text) == source
