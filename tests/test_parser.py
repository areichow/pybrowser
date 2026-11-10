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
