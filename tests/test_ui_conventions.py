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


def test_world_switch_invalidates_old_index_before_tree_mutation():
    source = Path("pybrowser/main_window.py").read_text()
    method = source[source.index("    def open_world_path"):source.index("    def _watch_none", source.index("    def open_world_path"))]
    assert method.index("self.index_cancelled.set()") < method.index("self._populate_module_tree()")
    assert method.index("self.index_generation += 1") < method.index("self._populate_module_tree()")


def test_large_world_results_are_batched_and_tree_lookup_is_constant_time():
    indexing = Path("pybrowser/indexing.py").read_text()
    main = Path("pybrowser/main_window.py").read_text()
    assert "ProcessPoolExecutor" in indexing
    assert "BATCH_SIZE = 24" in indexing
    update = main[main.index("    def _update_module_tree_item"):main.index("    def _recent_worlds", main.index("    def _update_module_tree_item"))]
    assert "self.module_tree_items.get(target)" in update
    assert "while queue" not in update


def test_member_order_controls_and_sorting_are_present():
    source = Path("pybrowser/main_window.py").read_text()
    assert 'QRadioButton("File")' in source
    assert 'QRadioButton("Sort")' in source
    assert 'visible.sort(key=lambda item: item.label.casefold())' in source


def test_editor_supports_keyboard_and_wheel_zoom():
    source = Path("pybrowser/widgets/editor.py").read_text()
    assert "def change_font_size" in source
    assert "Qt.Key.Key_Equal" in source
    assert "Qt.Key.Key_Minus" in source
    assert "def wheelEvent" in source


def test_category_drag_target_has_explicit_highlight():
    source = Path("pybrowser/widgets/browser_lists.py").read_text()
    assert '#2f78c4' in source
    assert 'def _set_drop_target' in source


def test_all_editor_write_paths_use_shared_write_service():
    main = Path("pybrowser/main_window.py").read_text()
    file_view = Path("pybrowser/widgets/file_view.py").read_text()
    query = Path("pybrowser/widgets/code_query_dialog.py").read_text()
    workspace = Path("pybrowser/workspace.py").read_text()
    combined = main + file_view + query
    assert "workspace.write_service" in combined
    assert "SaveRequest(" in main
    assert "SaveRequest(" in file_view
    assert "SaveRequest(" in query
    assert "SourceWriteService" in workspace
    assert "journaled_atomic_write" not in combined
    assert "journaled_create_file" not in combined

def test_structural_undo_redo_actions_and_history_controls_exist():
    main = Path("pybrowser/main_window.py").read_text()
    history = Path("pybrowser/widgets/structural_history.py").read_text()
    workspace = Path("pybrowser/workspace.py").read_text()
    assert 'setShortcut("Ctrl+Alt+Z")' in main
    assert 'setShortcut("Ctrl+Alt+Y")' in main
    assert 'QPushButton("Undo Selected")' in history
    assert 'QPushButton("Redo Selected")' in history
    assert "unsaved_windows_for" in workspace
    assert "restore_journal_location" in main


def test_incomplete_recovery_actions_are_exposed_in_history():
    history = Path("pybrowser/widgets/structural_history.py").read_text()
    assert 'QPushButton("Mark Not Applied")' in history
    assert 'QPushButton("Finalize Transaction")' in history
    assert 'QPushButton("Mark Reviewed")' in history
    assert 'resolve_incomplete(tx, action)' in history
