from pathlib import Path
from pybrowser.navigation import Location, NavigationHistory, search_file, symbols_for_module
from pybrowser.parser import build_index


def test_navigation_history_back_and_forward():
    history = NavigationHistory()
    one = Location(Path("a.py"), "<module>", "Functions", "one")
    two = Location(Path("b.py"), "App", "jobs", "two")
    history.visit(one)
    history.visit(two)
    assert history.back() == one
    assert history.forward() == two


def test_symbol_entries_and_project_search(tmp_path):
    path = tmp_path / "app.py"
    text = "def run():\n    return 'needle'\n"
    path.write_text(text)
    scopes = build_index(path, text)
    symbols = symbols_for_module(path, "app", scopes)
    assert symbols[0].label.startswith("run")
    results = search_file(path, "app", "needle")
    assert results[0].line == 2
    assert results[0].column == 13
