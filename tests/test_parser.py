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
