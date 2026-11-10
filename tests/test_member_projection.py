from pathlib import Path

import pytest

from pybrowser.member_projection import (
    file_to_editor_offset,
    project_member,
    project_source,
    restore_member,
)
from pybrowser.model import Document
from pybrowser.parser import build_index, read_document, replacement, validate
from pybrowser.recovery import RecoveryJournal
from pybrowser.source_write_service import SaveRequest, SourceWriteService


def document(text, newline="\n"):
    scopes = build_index(Path("app.py"), text)
    return Document(Path("app.py"), text, "utf-8", newline,
                    text.endswith(("\n", "\r")), (0, 0, ""), scopes)


def member_for(text, scope_name, label_prefix=None):
    doc = document(text, "\r\n" if "\r\n" in text else "\n")
    scope = next(scope for scope in doc.scopes if scope.name == scope_name)
    members = [member for member in scope.members if not member.synthetic]
    member = next((item for item in members if not label_prefix or item.label.startswith(label_prefix)), members[0])
    return doc, member


FIXTURES = (
    ("module", "def run():\n    return 1\n", "<module>"),
    ("class", "class App:\n    def run(self):\n        return 1\n", "App"),
    ("nested", "class Outer:\n    class Inner:\n        def run(self):\n            return 1\n", "Outer.Inner"),
    ("decorated-async", "class App:\n    @classmethod\n    async def run(cls):\n        return cls()\n", "App"),
    ("multiline-signature", "class App:\n    def run(\n        self,\n        value: int,\n    ):\n        return value\n", "App"),
    ("blank-lines", "class App:\n    def run(self):\n\n        return 1\n", "App"),
    ("triple-string", 'class App:\n    def run(self):\n        text = """first\n        indented text\n    closing"""\n        return text\n', "App"),
    ("continuation", "class App:\n    def run(self):\n        value = (\n            1 +\n            2\n        )\n        return value\n", "App"),
    ("nested-function", "class App:\n    def run(self):\n        def inner():\n            return 1\n        return inner()\n", "App"),
    ("nested-class", "class App:\n    def run(self):\n        class Local:\n            pass\n        return Local\n", "App"),
    ("crlf", "class App:\r\n    def run(self):\r\n        return 1\r\n", "App"),
)


@pytest.mark.parametrize("_name,text,scope_name", FIXTURES, ids=[item[0] for item in FIXTURES])
def test_every_projection_fixture_round_trips(_name, text, scope_name):
    doc, member = member_for(text, scope_name)
    projection = project_member(doc, member)
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


def test_unsafe_mixed_prefix_falls_back_to_literal_source():
    source = "    def run(self):\n\treturn 1\n"
    projection = project_source(source)
    assert not projection.projected
    assert projection.text == source
    assert restore_member(projection, projection.text) == source


@pytest.mark.parametrize(
    "encoding,newline,raw",
    [
        ("iso-8859-1", "\r\n", b"# coding: latin-1\r\nclass App:\r\n    def name(self):\r\n        return 'caf\xe9'\r\n"),
        ("utf-8", "\r\n", b"class App:\r\n    def name(self):\r\n        return 'cafe'\r\n"),
    ],
    ids=["latin1-crlf", "utf8-crlf"],
)
def test_projected_save_through_source_write_service_preserves_bytes(tmp_path, encoding, newline, raw):
    path = tmp_path / "app.py"
    path.write_bytes(raw)
    doc = read_document(path)
    scope = next(item for item in doc.scopes if item.name == "App")
    member = next(item for item in scope.members if item.label.startswith("name"))
    projection = project_member(doc, member)
    edited = projection.text.replace("return ", "value = ").replace("'cafe'", "'cafe'\n    return value").replace("'café'", "'thé'\n    return value")
    candidate = replacement(doc, member, restore_member(projection, edited))
    service = SourceWriteService(RecoveryJournal(tmp_path, tmp_path / "history"))
    result = service.save_document(SaveRequest(doc, candidate, "save_member", "Projected save"))
    data = path.read_bytes()
    assert result.transaction.status == "committed"
    assert result.document.encoding == encoding
    assert result.document.newline == newline
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")
    assert data.decode(encoding) == result.document.text


def test_diagnostic_file_offset_maps_to_projected_editor_offset():
    text = "class App:\n    def run(self):\n        missing()\n"
    doc, member = member_for(text, "App")
    projection = project_member(doc, member)
    literal = doc.source(member)
    file_offset = literal.index("missing")
    editor_offset = file_to_editor_offset(literal, file_offset, projection.prefix)
    assert projection.text[editor_offset:editor_offset + len("missing")] == "missing"
    assert editor_offset == projection.text.index("missing")
