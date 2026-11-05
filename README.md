# PyBrowser Revision 4

Revision 4 adds directory worlds and hierarchical Python package browsing while retaining single-file mode.

## Stage 4 features

- Open a project folder with **Ctrl+Shift+O**.
- Display packages, directories, and `.py` modules as a hierarchical tree.
- Derive dotted module names and show them in module tooltips.
- Exclude `.git`, `.venv`, `venv`, `__pycache__`, build, dist, pytest, mypy, Ruff, tox, nox, and Node-generated trees.
- Parse modules lazily when selected rather than blocking on every file in a repository.
- Watch project directories for module creation and deletion.
- Watch the current source file and reload clean editor sessions after external changes.
- Retain SHA-256 conflict protection for unsaved edits.
- Store up to ten recent files or worlds with `QSettings`.
- Preserve all Revision 3.2 browsing, editing, dark theme, and Find behavior.

## Run

```powershell
py -3.14 -m pip install -e .[dev]
py -3.14 -m pybrowser
py -3.14 -m pytest
```
