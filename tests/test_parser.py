from pathlib import Path
import pytest
from pybrowser.model import Document
from pybrowser.parser import ParseError,build_index,replacement,validate
SOURCE='''# category: Imports
import os
import sys

# category: Application
@decorator
class App:
    # category: initialization
    def __init__(
        self,
        value: str,
    ):
        self.value = value

    # category: jobs
    async def run(self):
        return 1

# category: Functions
def main():
    return App("x")
'''
def test_categories_decorators_async_and_multiline():
    scopes=build_index(Path("x.py"),SOURCE);assert [s.name for s in scopes]==["<module>","App"]
    assert scopes[1].members[0].category=="initialization";assert scopes[1].members[1].label.startswith("async run")
def test_category_does_not_leak():
    scopes=build_index(Path("x.py"),"# category: One\ndef one(): pass\n\ndef two(): pass\n")
    assert [m.category for m in scopes[0].members]==["One","-- functions --"]
def test_replacement_preserves_unrelated_bytes():
    scopes=build_index(Path("x.py"),SOURCE);m=scopes[0].members[-1];doc=Document(Path("x.py"),SOURCE,"utf-8","\n",True,(0,0,""),scopes);candidate=replacement(doc,m,"# category: Functions\ndef main():\n    return 42\n");assert candidate.startswith(SOURCE[:m.span.start]);assert "return 42" in candidate;validate(candidate,"x.py")
def test_invalid_source_reports_location():
    with pytest.raises(ParseError) as info:validate("def broken(:\n pass\n","x.py")
    assert info.value.line is not None



def test_indented_member_span_uses_literal_document_offsets():
    text = "class App:\r\n    def run(self):\r\n        return 1\r\n\r\n    def run(self):\r\n        return 2\r\n"
    scope = next(item for item in build_index(Path("x.py"), text) if item.name == "App")
    first, second = scope.members
    assert first.span.start == text.index("    def run(self):")
    assert second.span.start == text.rindex("    def run(self):")
    assert text[second.span.start:second.span.end].lstrip().startswith("def run(self):")


def test_body_only_rebase_updates_following_offsets_without_reparse():
    from pybrowser.parser import rebase_member_document
    text = "class App:\n    def first(self):\n        return 1\n\n    def second(self):\n        return 2\n"
    scopes = build_index(Path("x.py"), text)
    document = Document(Path("x.py"), text, "utf-8", "\n", True, (0, 0, ""), scopes)
    scope = next(item for item in scopes if item.name == "App")
    first, second = scope.members
    restored = "    def first(self):\n        value = 1\n        return value\n"
    candidate = replacement(document, first, restored)
    rebased = rebase_member_document(document, first, restored, candidate)
    assert rebased is not None
    new_scope = next(item for item in rebased if item.name == "App")
    assert candidate[new_scope.members[0].span.start:new_scope.members[0].span.end] == restored
    assert candidate[new_scope.members[1].span.start:new_scope.members[1].span.end].lstrip().startswith("def second")
    assert new_scope.members[1].span.first == second.span.first + 1


def test_header_change_refuses_body_only_rebase():
    from pybrowser.parser import rebase_member_document
    text = "def run(value):\n    return value\n"
    scopes = build_index(Path("x.py"), text)
    document = Document(Path("x.py"), text, "utf-8", "\n", True, (0, 0, ""), scopes)
    member = scopes[0].members[0]
    restored = "def renamed(value):\n    return value\n"
    assert rebase_member_document(document, member, restored,
                                  replacement(document, member, restored)) is None


def test_ast_shape_fast_path_accepts_decorated_multiline_method_body_change():
    from pybrowser.parser import rebase_member_document
    text = """class App:\n    @decorator(flag=True)\n    async def run(\n        self,\n        value: list[str],\n    ) -> str:\n        return value[0]\n"""
    scopes = build_index(Path("x.py"), text)
    document = Document(Path("x.py"), text, "utf-8", "\n", True,
                        (0, 0, ""), scopes)
    scope = next(item for item in scopes if item.name == "App")
    member = scope.members[0]
    restored = """    @decorator(flag=True)\n    async def run(\n        self,\n        value: list[str],\n    ) -> str:\n        answer = value[0]\n        return answer\n"""
    candidate = replacement(document, member, restored)
    rebased, reason = rebase_member_document(
        document, member, restored, candidate, with_reason=True)
    assert rebased is not None
    assert reason == ""


def test_ast_shape_fast_path_reports_signature_rejection_reason():
    from pybrowser.parser import rebase_member_document
    text = "def run(value: int) -> int:\n    return value\n"
    scopes = build_index(Path("x.py"), text)
    document = Document(Path("x.py"), text, "utf-8", "\n", True,
                        (0, 0, ""), scopes)
    member = scopes[0].members[0]
    restored = "def run(value: str) -> int:\n    return len(value)\n"
    rebased, reason = rebase_member_document(
        document, member, restored,
        replacement(document, member, restored), with_reason=True)
    assert rebased is None
    assert reason == "callable declaration or decorators changed"

@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_rebase_uses_exact_replacement_slice_when_editor_omits_final_newline(newline):
    from pybrowser.parser import rebase_member_document
    text = newline.join((
        "class App:",
        "    def first(self):",
        "        self.do_pending_operations(model)",
        "",
        "    def second(self):",
        "        self.clear_cache()",
        "",
    ))
    scopes = build_index(Path("x.py"), text)
    document = Document(Path("x.py"), text, "utf-8", newline, True,
                        (0, 0, ""), scopes)
    scope = next(item for item in scopes if item.name == "App")
    first = scope.members[0]
    # QPlainTextEdit.toPlainText() omits the Member span's terminating newline.
    projected_edit = newline.join((
        "    def first(self):",
        "        print('test')",
        "        self.do_pending_operations(model)",
    ))
    candidate = replacement(document, first, projected_edit)
    rebased = rebase_member_document(document, first, projected_edit, candidate)
    assert rebased is not None
    updated = next(item for item in rebased if item.name == "App")
    first_after, second_after = updated.members
    assert candidate[first_after.span.start:first_after.span.end].endswith(newline)
    assert candidate[second_after.span.start:second_after.span.end].lstrip().startswith("def second")
    assert "self.do_pending_operations(model)" + newline + newline + "    def second" in candidate
    validate(candidate, "x.py")


def test_three_consecutive_fast_rebases_keep_member_boundaries_exact():
    from pybrowser.parser import rebase_member_document
    text = "class App:\n    def first(self):\n        return 1\n\n    def second(self):\n        return 2\n"
    document = Document(Path("x.py"), text, "utf-8", "\n", True,
                        (0, 0, ""), build_index(Path("x.py"), text))
    for value in ("one", "one.one", ""):
        scope = next(item for item in document.scopes if item.name == "App")
        member = scope.members[0]
        body = f"    def first(self):\n        print({value!r})\n        return 1" if value else "    def first(self):\n        return 1"
        candidate = replacement(document, member, body)
        scopes = rebase_member_document(document, member, body, candidate)
        assert scopes is not None
        document = Document(document.path, candidate, document.encoding,
                            document.newline, True, document.signature, scopes)
        validate(document.text, "x.py")
        current = next(item for item in scopes if item.name == "App")
        assert document.source(current.members[0]).endswith("\n")
        assert document.source(current.members[1]).lstrip().startswith("def second")
