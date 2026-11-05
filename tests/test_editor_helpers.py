import pytest
pytest.importorskip("PySide6")
from pybrowser.widgets.editor import Editor


def test_matching_brackets_nested():
    text = "call(a[0], {'x': 1})"
    assert Editor._matching_bracket(text, 4) == len(text) - 1
    square = text.index("[")
    assert Editor._matching_bracket(text, square) == text.index("]")


def test_matching_bracket_none_for_unbalanced():
    assert Editor._matching_bracket("func(", 4) is None
