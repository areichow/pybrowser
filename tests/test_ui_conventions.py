from pathlib import Path


def test_window_shortcuts_are_explicit_ctrl_sequences():
    source = Path("pybrowser/windowing.py").read_text()
    assert 'QKeySequence("Ctrl+W")' in source
    assert 'QKeySequence("Ctrl+Q")' in source
    assert "StandardKey.Close" not in source


def test_main_interface_uses_member_language():
    source = Path("pybrowser/main_window.py").read_text()
    assert "Current Member only" in source
    assert "Abandon Member Changes" in source
    assert "method/entity" not in source
