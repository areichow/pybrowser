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


def test_unsaved_yellow_precedes_duplicate_warning_color():
    source = Path("pybrowser/widgets/member_delegate.py").read_text()
    assert 'unsaved = ' in source
    assert source.index("elif unsaved:") < source.index("elif duplicate:")


def test_world_refresh_preserves_complete_browser_bookmark():
    source = Path("pybrowser/main_window.py").read_text()
    refresh = source[source.index("    def _refresh_world"):source.index("    def _file_changed", source.index("    def _refresh_world"))]
    assert "_capture_browser_selection()" in refresh
    assert "_restore_browser_bookmark(bookmark)" in refresh


def test_programmatic_module_selection_blocks_reset_signal():
    source = Path("pybrowser/main_window.py").read_text()
    method = source[source.index("    def _select_module_path"):source.index("    def _watch_world", source.index("    def _select_module_path"))]
    assert "QSignalBlocker(self.modules)" in method
    assert "fallback_row=fallback_row" in method


def test_workspace_writer_does_not_reload_its_own_save_broadcast():
    source = Path("pybrowser/main_window.py").read_text()
    method = source[source.index("    def _workspace_file_changed"):source.index("    def _members_context_menu", source.index("    def _workspace_file_changed"))]
    assert "if origin is self:" in method
