from pathlib import Path


def test_window_shortcuts_are_explicit_ctrl_sequences():
    source = Path("pybrowser/windowing.py").read_text(encoding="utf-8")
    assert 'QKeySequence("Ctrl+W")' in source
    assert 'QKeySequence("Ctrl+Q")' in source
    assert "StandardKey.Close" not in source


def test_main_interface_uses_member_language():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    assert "Current Member only" in source
    assert "Abandon Member Changes" in source
    assert "method/entity" not in source


def test_save_and_structural_reload_clear_modified_before_reselection():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    save = source[source.index("    def save(self):"):source.index("    def _highlight_error", source.index("    def save(self):"))]
    assert save.index("setModified(False)") < save.index("_open_module(")
    structural = source[source.index("    def _apply_structural_edit"):source.index("    def new_function", source.index("    def _apply_structural_edit"))]
    assert "fallback_row" in structural
    assert "_select_location" in structural


def test_duplicate_members_use_light_red_marker():
    source = Path("pybrowser/widgets/member_delegate.py").read_text(encoding="utf-8")
    assert "#dca8ac" in source
    assert "duplicate-definition" in source


def test_unsaved_yellow_precedes_duplicate_warning_color():
    source = Path("pybrowser/widgets/member_delegate.py").read_text(encoding="utf-8")
    assert 'unsaved = ' in source
    assert source.index("elif unsaved:") < source.index("elif duplicate:")


def test_world_refresh_preserves_complete_browser_bookmark():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    refresh = source[source.index("    def _refresh_world"):source.index("    def _file_changed", source.index("    def _refresh_world"))]
    assert "_capture_browser_selection()" in refresh
    assert "_restore_browser_bookmark(bookmark)" in refresh


def test_programmatic_module_selection_blocks_reset_signal():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    method = source[source.index("    def _select_module_path"):source.index("    def _watch_world", source.index("    def _select_module_path"))]
    assert "QSignalBlocker(self.modules)" in method
    assert "fallback_row=fallback_row" in method


def test_workspace_writer_does_not_reload_its_own_save_broadcast():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    method = source[source.index("    def _workspace_file_changed"):source.index("    def _members_context_menu", source.index("    def _workspace_file_changed"))]
    assert "if origin is self:" in method


def test_world_switch_invalidates_old_index_before_tree_mutation():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    method = source[source.index("    def open_world_path"):source.index("    def _watch_none", source.index("    def open_world_path"))]
    assert method.index("self.index_cancelled.set()") < method.index("self._populate_module_tree()")
    assert method.index("self.index_generation += 1") < method.index("self._populate_module_tree()")


def test_large_world_results_are_batched_and_tree_lookup_is_constant_time():
    indexing = Path("pybrowser/indexing.py").read_text(encoding="utf-8")
    main = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    assert "ProcessPoolExecutor" in indexing
    assert "BATCH_SIZE = 24" in indexing
    update = main[main.index("    def _update_module_tree_item"):main.index("    def _recent_worlds", main.index("    def _update_module_tree_item"))]
    assert "self.module_tree_items.get(target)" in update
    assert "while queue" not in update


def test_member_order_controls_and_sorting_are_present():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    assert 'QRadioButton("File")' in source
    assert 'QRadioButton("Sort")' in source
    assert 'visible.sort(key=lambda item: item.label.casefold())' in source


def test_editor_supports_keyboard_and_wheel_zoom():
    source = Path("pybrowser/widgets/editor.py").read_text(encoding="utf-8")
    assert "def change_font_size" in source
    assert "Qt.Key.Key_Equal" in source
    assert "Qt.Key.Key_Minus" in source
    assert "def wheelEvent" in source


def test_category_drag_target_has_explicit_highlight():
    source = Path("pybrowser/widgets/browser_lists.py").read_text(encoding="utf-8")
    assert '#2f78c4' in source
    assert 'def _set_drop_target' in source


def test_all_editor_write_paths_use_shared_write_service():
    main = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    file_view = Path("pybrowser/widgets/file_view.py").read_text(encoding="utf-8")
    query = Path("pybrowser/widgets/code_query_dialog.py").read_text(encoding="utf-8")
    workspace = Path("pybrowser/workspace.py").read_text(encoding="utf-8")
    combined = main + file_view + query
    assert "workspace.write_service" in combined
    assert "SaveRequest(" in main
    assert "SaveRequest(" in file_view
    assert "SaveRequest(" in query
    assert "SourceWriteService" in workspace
    assert "journaled_atomic_write" not in combined
    assert "journaled_create_file" not in combined

def test_structural_undo_redo_actions_and_history_controls_exist():
    main = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    history = Path("pybrowser/widgets/structural_history.py").read_text(encoding="utf-8")
    workspace = Path("pybrowser/workspace.py").read_text(encoding="utf-8")
    assert 'setShortcut("Ctrl+Alt+Z")' in main
    assert 'setShortcut("Ctrl+Alt+Y")' in main
    assert 'QPushButton("Undo Selected")' in history
    assert 'QPushButton("Redo Selected")' in history
    assert "unsaved_windows_for" in workspace
    assert "restore_journal_location" in main


def test_incomplete_recovery_actions_are_exposed_in_history():
    history = Path("pybrowser/widgets/structural_history.py").read_text(encoding="utf-8")
    assert 'QPushButton("Mark Not Applied")' in history
    assert 'QPushButton("Finalize Transaction")' in history
    assert 'QPushButton("Mark Reviewed")' in history
    assert 'resolve_incomplete(tx, action)' in history

def test_structural_edits_delegate_validation_and_conflicts_to_write_service():
    source = Path('pybrowser/main_window.py').read_text(encoding="utf-8")
    method = source[source.index('    def _apply_structural_edit'):source.index('    def _select_location', source.index('    def _apply_structural_edit'))]
    assert '\n            validate(' not in method
    assert '\n            if changed(' not in method
    assert 'result = self.workspace.write_service.save_document' in method
    assert 'except SourceConflictError' in method
    assert 'except SourcePostCommitError' in method
    assert 'result.warnings' in method


def test_duplicate_success_selects_identifier_for_rename():
    source = Path('pybrowser/main_window.py').read_text(encoding="utf-8")
    assert 'def _select_member_identifier' in source
    assert 'self._select_member_identifier()' in source
    assert 'Rename the selected copy and press Ctrl+S.' in source


def test_window_menu_disconnects_before_owner_deletion():
    source = Path("pybrowser/windowing.py").read_text(encoding="utf-8")
    assert "from shiboken6 import isValid" in source
    assert "workspace.windows_changed.disconnect(rebuild)" in source
    assert "window.destroyed.connect(disconnect_rebuild)" in source
    assert "if not isValid(window) or not isValid(menu)" in source

def test_workspace_destroy_callback_does_not_capture_deleted_window_wrapper():
    source = Path("pybrowser/workspace.py").read_text(encoding="utf-8")
    assert "window.destroyed.connect(self._window_destroyed)" in source
    assert "lambda: self._remove(window)" not in source
    assert "QCoreApplication.closingDown()" in source


def test_file_watcher_reload_preserves_duplicate_row_fallback():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    method = source[source.index("    def _file_changed"):source.index("    def _start_background_index", source.index("    def _file_changed"))]
    assert "fallback_row=self.members.currentRow()" in method
    assert "def _select_member_occurrence" in source


def test_duplicate_label_restore_prefers_matching_fallback_row():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    method = source[source.index("    def _select_location"):source.index("    def _select_structural_result", source.index("    def _select_location"))]
    assert "fallback_row in matching_rows" in method
    assert "row = fallback_row" in method

def test_duplicate_restore_matching_rows_is_always_initialized():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    method = source[source.index("    def _select_location"):source.index("    def _select_structural_result", source.index("    def _select_location"))]
    assert "matching_rows = []" in method
    assert "fallback_row in matching_rows" in method
    assert method.index("matching_rows = []") < method.index("fallback_row in matching_rows")


def test_index_worker_does_not_swallow_base_exception():
    source = Path("pybrowser/indexing.py").read_text(encoding="utf-8")
    assert "except BaseException" not in source
    assert "except Exception as exc" in source


def test_duplicate_identifier_selection_occurs_after_occurrence_restoration():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    method = source[source.index("    def _apply_structural_edit"):source.index("    def _select_location", source.index("    def _apply_structural_edit"))]
    assert method.index("self._select_member_occurrence") < method.index("self._select_member_identifier()")


def test_diagnostic_navigation_maps_literal_member_offset_into_projection():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    method = source[source.index("    def _select_line_result"):source.index("    def navigate_back", source.index("    def _select_line_result"))]
    assert "file_to_editor_offset" in method
    assert "self.member_projection.prefix" in method
    assert method.index("self._select_browser_member(member)") < method.index("file_to_editor_offset")


def test_manual_commit_file_menu_and_quit_disposition_exist():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    assert 'QAction("Auto-Commit Enabled"' in source
    assert 'QAction("Commit Changes to Disk"' in source
    assert 'QAction("View Staged Changes"' in source
    assert 'QAction("Abandon Staged Changes...' in source
    assert 'box.addButton("Commit Changes"' in source
    assert 'box.addButton("Abandon Changes"' in source
    assert 'box.addButton("View Changes"' in source
    assert 'QMessageBox.StandardButton.Cancel' in source


def test_typecheck_refuses_stale_disk_when_overlay_exists():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    method = source[source.index("    def run_type_check"):source.index("    def _typecheck_finished", source.index("    def run_type_check"))]
    assert "self.workspace.staged_paths()" in method
    assert "Type checking is unavailable" in method


def test_manual_stage_publication_does_not_reload_origin_mid_save():
    service = Path("pybrowser/source_write_service.py").read_text(encoding="utf-8")
    workspace = Path("pybrowser/workspace.py").read_text(encoding="utf-8")
    assert "notify=False" in service
    assert "self.notify(path, request.origin)" in service
    assert "self.world_changed.emit(self.effective_world())" in workspace


def test_gui_regression_isolates_manual_commit_setting_and_modal_exec():
    source = Path("tests/test_structural_gui.py").read_text(encoding="utf-8")
    assert 'settings.setValue("source/writeMode", WriteMode.AUTO_COMMIT.value)' in source
    assert 'monkeypatch.setattr(QMessageBox, "exec", unexpected)' in source


def test_view_staged_changes_opens_dedicated_window():
    main = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    staged = Path("pybrowser/widgets/staged_changes.py").read_text(encoding="utf-8")
    assert "view_staged_action.triggered.connect(self.show_staged_changes)" in main
    assert "class StagedChangesWindow" in staged
    for label in ("Commit Selected", "Abandon Selected...", "Open Staged Source",
                  "Commit All", "Abandon All...", "Refresh"):
        assert label in staged
    assert "Physical file differs from the staged baseline" in staged
    assert "Virtual target is still absent from disk" in staged


def test_quit_view_changes_uses_staged_changes_window():
    source = Path("pybrowser/main_window.py").read_text(encoding="utf-8")
    method = source[source.index("    def _staged_exit_disposition"):source.index(
        "    def run_type_check", source.index("    def _staged_exit_disposition"))]
    assert "self.show_staged_changes()" in method
    assert "self.show_structural_history()" not in method


def test_staged_changes_window_uses_bound_slot_and_delete_on_close():
    source = Path("pybrowser/widgets/staged_changes.py").read_text(encoding="utf-8")
    assert "WA_DeleteOnClose" in source
    assert "world_changed.connect(self._world_changed)" in source
    assert "world_changed.connect(lambda" not in source
    assert 'fromfile="baseline/"' in source
    assert "Only active staged files are listed" in source


def test_staged_finalization_housekeeping_returns_warnings():
    recovery = Path("pybrowser/recovery.py").read_text(encoding="utf-8")
    service = Path("pybrowser/source_write_service.py").read_text(encoding="utf-8")
    assert "class StagedCompletionResult" in recovery
    assert "Portable manifest repair failed" in recovery
    assert "History notification failed" in recovery
    assert "completion.warnings" in service
