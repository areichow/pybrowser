import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMainWindow
from shiboken6 import isValid

from pybrowser.main_window import MainWindow
from pybrowser.project import open_world
from pybrowser.widgets.staged_changes import StagedChangesWindow
from pybrowser.windowing import install_window_commands
from pybrowser.workspace import Workspace


@pytest.fixture(scope="module")
def app():
    value = QApplication.instance() or QApplication([])
    value.setQuitOnLastWindowClosed(False)
    yield value
    value.processEvents()


def flush_delete(app):
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_deleted_staged_changes_is_compacted_and_can_reopen(tmp_path, app, monkeypatch):
    path = tmp_path / "app.py"
    path.write_bytes(b"VALUE = 1\n")
    workspace = Workspace(); workspace.set_world(open_world(path))
    browser = MainWindow(workspace=workspace)
    monkeypatch.setattr(browser, "_start_background_index", lambda: None)
    first = StagedChangesWindow(workspace)
    browser.child_windows.append(first)
    first.show(); app.processEvents()
    assert first in workspace.open_windows()

    first.close(); first.deleteLater(); flush_delete(app)
    assert not isValid(first)
    assert first not in workspace.open_windows()

    browser.show_staged_changes(); app.processEvents()
    reopened = next(window for window in workspace.open_windows()
                    if getattr(window, "window_kind", "") == "staged-changes")
    assert isValid(reopened)

    workspace.unregister(reopened, emit=False)
    reopened.close(); reopened.deleteLater()
    workspace.unregister(browser, emit=False)
    browser.close(); browser.deleteLater(); flush_delete(app)


def test_window_menu_rebuild_survives_deleted_registry_entries(app):
    workspace = Workspace()
    owner = QMainWindow(); workspace.register(owner, "browser")
    file_menu = owner.menuBar().addMenu("&File")
    install_window_commands(owner, workspace, file_menu)
    deleted = QMainWindow(); workspace.register(deleted, "file-view")
    deleted.show(); app.processEvents()
    deleted.close(); deleted.deleteLater(); flush_delete(app)
    assert not isValid(deleted)

    # This emitted signal previously invoked every Window-menu rebuild and
    # raised while open_windows() called isHidden() on the deleted wrapper.
    workspace.windows_changed.emit(); app.processEvents()
    assert workspace.open_windows() == [] or workspace.open_windows() == [owner]

    workspace.unregister(owner, emit=False)
    owner.close(); owner.deleteLater(); flush_delete(app)


def test_open_windows_compacts_an_explicit_deleted_wrapper(app):
    workspace = Workspace()
    window = QMainWindow(); workspace.register(window)
    window.deleteLater(); flush_delete(app)
    assert not isValid(window)
    # Retain the invalid wrapper deliberately to exercise defensive compaction.
    workspace.windows.append(window)
    assert workspace.open_windows() == () or workspace.open_windows() == []
    assert workspace.windows == []
