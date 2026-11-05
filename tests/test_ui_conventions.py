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


def test_save_and_structural_reload_clear_modified_before_reselection():
    source = Path("pybrowser/main_window.py").read_text()
    save = source[source.index("    def save(self):"):source.index("    def _highlight_error", source.index("    def save(self):"))]
    assert save.index("setModified(False)") < save.index("_open_module(")
    structural = source[source.index("    def _apply_structural_edit"):source.index("    def new_function", source.index("    def _apply_structural_edit"))]
    assert "fallback_row" in structural
    assert "_select_location" in structural


def test_duplicate_members_use_light_red_marker():
    source = Path("pybrowser/widgets/member_delegate.py").read_text()
    assert "#dca8ac" in source
    assert "duplicate-definition" in source
