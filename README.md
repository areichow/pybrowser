# PyBrowser Revision 9

Revision 9 adds optional BasedPyright and Pyright type diagnostics without making either checker a required dependency.

## Type checking

- **Tools > Run Type Check** or `Ctrl+Shift+T` analyzes the open file or directory world in a background `QThreadPool` task.
- Auto-discovery prefers `basedpyright`, then `pyright`, using PATH or the active Python interpreter's Scripts/bin directory.
- **Tools > Type Checker Settings** selects auto, BasedPyright, or Pyright; allows an executable override; and optionally passes a Python interpreter through `--pythonpath`.
- The collapsible Diagnostics panel shows severity, file/line/column, diagnostic rule, and message.
- Double-clicking a diagnostic opens its module and containing browser entity.
- Unsaved entity edits must be saved or abandoned before analysis, so reported source locations stay valid.
- Fatal startup, timeout, configuration, and malformed-output failures are shown without affecting ordinary browsing or editing.

PyBrowser invokes the checker's documented `--outputjson` CLI format. Project configuration remains owned by `pyrightconfig.json` or `[tool.pyright]` in `pyproject.toml`.

Install one optional checker:

```powershell
py -3.14 -m pip install basedpyright
basedpyright --version
```

or install Pyright and make its `pyright` command available on PATH.

## Run

```powershell
py -3.14 -m pip install -e .[dev]
py -3.14 -m pybrowser
py -3.14 -m pytest
```


## Revision 9.1 browser conventions and context actions

- Members context menu now exposes Move to category, Duplicate, Delete, Implementers, Senders, and method-kind conversion where applicable.
- Categories context menu exposes Rename category and New method in category. Built-in inferred categories cannot be renamed.
- Removed Structure > New Category because categories have no independent source representation; a category is created by adding or moving its first member.
- Built-in categories use Smalltalk-style names and sort first: `-- imports --`, `-- constants --`, `-- docs --`, `-- functions --`, and `-- variables --`.
- Uncategorized class members appear under `as yet unclassified`.
- The module scope displays as `-- module --` while retaining its internal structural identity.
- Synthetic category block members display as `-- entire category --`.


## Revision 10 shared workspace and contextual file editing

- Modules, Scopes, Categories, and Members context menus include **View in file...**, opening an editable whole-file window positioned at the selected structure.
- File View supports `Ctrl+S` and `Ctrl+L`, validates the complete module, writes atomically, and broadcasts changes to every window in the workspace.
- Members can be dragged onto an existing category to move them without a category-name prompt.
- **Tools > New Browser** (`Ctrl+Shift+B`) opens another browser on the same shared world.
- `Ctrl+B` in a code editor opens another browser on the selected class name when the class is indexed.
- Implementers and Senders windows are modeless, editable, and support `Ctrl+S` and `Ctrl+L`; saved changes refresh browser and file-view windows.
- Scopes context menus include **New Class...**. Categories context menus include **New Method...** and **New Function...**.


## Revision 10.1 responsive source model and query edit indicators

- Adds an always-visible Source Model activity strip with operation text and determinate progress for module indexing, Implementers, Senders, and Find in World.
- Moves Implementers, Senders, and world-wide text scans onto `QThreadPool` workers. The Qt UI thread now only receives progress and final immutable results.
- Long-running world scans report the current module and completed/total counts.
- Implementers and Senders windows show a bright yellow `Unsaved changes` banner, bold/yellow current result, and the standard modified-window marker until Ctrl+S or Ctrl+L clears the edit.
- Existing background indexing now reports through the same activity strip rather than only the transient status bar.
