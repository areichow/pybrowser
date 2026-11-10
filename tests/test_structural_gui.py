import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from pybrowser.main_window import MainWindow
from pybrowser.workspace import Workspace
from pybrowser.source_write_service import WriteMode


@pytest.fixture(scope="module")
def app():
    value = QApplication.instance() or QApplication([])
    value.setQuitOnLastWindowClosed(False)
    yield value
    value.processEvents()


@pytest.fixture
def auto_commit_setting():
    settings = QSettings("PyBrowser", "PyBrowser")
    previous = settings.value("source/writeMode", None)
    settings.setValue("source/writeMode", WriteMode.AUTO_COMMIT.value)
    settings.sync()
    yield
    if previous is None:
        settings.remove("source/writeMode")
    else:
        settings.setValue("source/writeMode", previous)
    settings.sync()


@pytest.fixture
def no_modal_dialogs(monkeypatch):
    def unexpected(*args, **kwargs):
        title = args[1] if len(args) > 1 else "Qt dialog"
        text = args[2] if len(args) > 2 else ""
        pytest.fail(f"Unexpected modal dialog: {title}: {text}")
    for name in ("critical", "warning", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, unexpected)
    monkeypatch.setattr(QMessageBox, "exec", unexpected)


def _select_member(window, scope_name, member_name):
    scope_row = next(i for i in range(window.scopes.count()) if scope_name in window.scopes.item(i).text())
    window.scopes.setCurrentRow(scope_row)
    category_row = next(i for i in range(window.categories.count()) if window.categories.item(i).text() == "as yet unclassified")
    window.categories.setCurrentRow(category_row)
    member_row = next(i for i in range(window.members.count()) if window.members.item(i).text().lstrip("✕▲●0123456789 ").startswith(member_name))
    window.members.setCurrentRow(member_row)


def test_duplicate_then_rename_changes_only_inserted_method(tmp_path, app, monkeypatch, no_modal_dialogs, auto_commit_setting):
    # This is a focused GUI behavior test. Process-pool indexing is unrelated and
    # can keep spawned Windows workers alive after the Qt window is gone.
    monkeypatch.setattr(MainWindow, "_start_background_index", lambda self: None)
    monkeypatch.setattr(MainWindow, "_watch_world", lambda self: None)
    monkeypatch.setattr(MainWindow, "_watch_current_file", lambda self: None)

    path = tmp_path / "app.py"
    path.write_text("class App:\n    def run(self):\n        return 1\n")
    workspace = Workspace()
    window = MainWindow(workspace=workspace)
    try:
        assert window.auto_commit_action.isChecked()
        window.open(path)
        app.processEvents()
        _select_member(window, "App", "run")
        app.processEvents()

        window.duplicate_current_member()
        app.processEvents()

        assert path.read_text().count("def run(self):") == 2
        assert window.members.currentRow() == window.members.count() - 1
        # Span offsets refer to Document.text, which preserves literal CRLF on
        # Windows. Path.read_text() performs universal-newline translation and
        # therefore cannot be used for offset comparisons.
        assert window.member.span.start == window.doc.text.rindex("    def run(self):")
        assert window.doc.source(window.member).lstrip().startswith("def run(self):")
        duplicate_cursor = window.editor.textCursor()
        assert duplicate_cursor.hasSelection()
        assert duplicate_cursor.selectedText() == "run"

        # Re-run the ambiguous label restoration directly, without starting
        # ProcessPoolExecutor or QFileSystemWatcher activity in this unit test.
        window._open_module(
            path,
            (window.member.scope, window.member.category, window.member.label),
            fallback_row=window.members.currentRow(),
        )
        app.processEvents()
        assert window.members.currentRow() == window.members.count() - 1
        assert window.member.span.start == window.doc.text.rindex("    def run(self):")
        assert window.doc.source(window.member).lstrip().startswith("def run(self):")

        # A general module reload restores structural identity, not an ephemeral
        # editor selection. Reapply the rename affordance before simulating typing.
        window._select_member_identifier()
        cursor = window.editor.textCursor()
        assert cursor.hasSelection() and cursor.selectedText() == "run"
        cursor.insertText("run_copy")
        window.editor.setTextCursor(cursor)
        window.save()
        app.processEvents()

        source = path.read_text()
        assert source.count("def run(self):") == 1
        assert source.count("def run_copy(self):") == 1
        operations = [tx.operation for tx in reversed(workspace.journal.transactions())]
        assert operations[-2:] == ["duplicate_member", "save_member"]
    finally:
        workspace.unregister(window, emit=False)
        window.close()
        window.deleteLater()
        app.sendPostedEvents()
        app.processEvents()

@pytest.mark.parametrize("write_mode", [WriteMode.AUTO_COMMIT, WriteMode.MANUAL_COMMIT],
                         ids=["auto-commit", "manual-commit"])
def test_repeated_member_saves_keep_following_member_boundary(
        tmp_path, app, monkeypatch, no_modal_dialogs, auto_commit_setting, write_mode):
    monkeypatch.setattr(MainWindow, "_start_background_index", lambda self: None)
    monkeypatch.setattr(MainWindow, "_watch_world", lambda self: None)
    monkeypatch.setattr(MainWindow, "_watch_current_file", lambda self: None)
    path = tmp_path / "app.py"
    path.write_bytes(
        b"class App:\n"
        b"    def first(self, model):\n"
        b"        self.do_pending_operations(model)\n\n"
        b"    def second(self):\n"
        b"        self.clear_cache()\n"
    )
    workspace = Workspace()
    window = MainWindow(workspace=workspace)
    try:
        window.open(path); app.processEvents()
        workspace.set_write_mode(write_mode)
        _select_member(window, "App", "first")
        for value in ('print("24.4 test 1")', 'print("24.4 test 1.1")', None):
            lines = ["def first(self, model):"]
            if value:
                lines.append("    " + value)
            lines.append("    self.do_pending_operations(model)")
            window.editor.setPlainText("\n".join(lines))
            window.editor.document().setModified(True)
            window.save(); app.processEvents()
            assert not window.editor.document().isModified()
            assert len(window.doc.scopes) >= 2
            scope = next(item for item in window.doc.scopes if item.name == "App")
            assert [item.label.split("  (", 1)[0] for item in scope.members] == ["first", "second"]
            assert window.doc.source(scope.members[0]).endswith("\n")
            assert window.doc.source(scope.members[1]).lstrip().startswith("def second")
            assert "self.do_pending_operations(model)\n\n    def second" in window.doc.text
            __import__("ast").parse(window.doc.text)
        if write_mode == WriteMode.AUTO_COMMIT:
            assert path.read_bytes() == window.doc.text.encode("utf-8")
        else:
            assert path.read_bytes().startswith(b"class App:\n")
            assert workspace.source_store.read_document(path).text == window.doc.text
    finally:
        workspace.unregister(window, emit=False)
        window.close(); window.deleteLater(); app.sendPostedEvents(); app.processEvents()
