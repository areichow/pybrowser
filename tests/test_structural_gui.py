import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextCursor
from pybrowser.main_window import MainWindow
from pybrowser.workspace import Workspace

@pytest.fixture(scope='module')
def app():
    value = QApplication.instance() or QApplication([])
    yield value

def _select_member(window, scope_name, member_name):
    scope_row = next(i for i in range(window.scopes.count()) if scope_name in window.scopes.item(i).text())
    window.scopes.setCurrentRow(scope_row)
    category_row = next(i for i in range(window.categories.count()) if window.categories.item(i).text() == 'as yet unclassified')
    window.categories.setCurrentRow(category_row)
    member_row = next(i for i in range(window.members.count()) if window.members.item(i).text().lstrip('✕▲●0123456789 ').startswith(member_name))
    window.members.setCurrentRow(member_row)

def test_duplicate_then_rename_changes_only_inserted_method(tmp_path, app):
    path=tmp_path/'app.py'
    path.write_text('class App:\n    def run(self):\n        return 1\n')
    workspace=Workspace(); window=MainWindow(workspace=workspace)
    window.open(path); app.processEvents()
    _select_member(window,'App','run'); app.processEvents()
    window.duplicate_current_member(); app.processEvents()
    assert path.read_text().count('def run(self):') == 2
    assert window.members.currentRow() == 1
    cursor=window.editor.textCursor()
    assert cursor.hasSelection() and cursor.selectedText() == 'run'
    cursor.insertText('run_copy'); window.editor.setTextCursor(cursor)
    window.save(); app.processEvents()
    source=path.read_text()
    assert source.count('def run(self):') == 1
    assert source.count('def run_copy(self):') == 1
    operations=[tx.operation for tx in reversed(workspace.journal.transactions())]
    assert operations[-2:] == ['duplicate_member','save_member']
    window.close()
