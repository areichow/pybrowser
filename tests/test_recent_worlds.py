from pathlib import Path


def test_recent_world_action_is_queued_outside_native_menu_callback():
    source = Path("pybrowser/main_window.py").read_text()
    remember = source[source.index("    def _remember_world"):source.index("    def _scope", source.index("    def _remember_world"))]
    assert "QTimer.singleShot(0, self._finish_open_recent_world)" in remember
    assert "self.open_world_path(Path(value))" in remember
    assert "self.recent_menu.isVisible()" in remember
    # Menu rebuild is deferred, not performed synchronously by _remember_world.
    body = remember[remember.index("    def _remember_world"):remember.index("    def _open_recent_world")]
    assert "QTimer.singleShot(0, self._rebuild_recent_menu)" in body
    assert "self._rebuild_recent_menu()" not in body


def test_windows_process_entry_is_guarded():
    source = Path("pybrowser/__main__.py").read_text()
    assert 'if __name__ == "__main__":' in source
    assert "freeze_support()" in source
