# PyBrowser

PyBrowser is a Smalltalk-inspired structural browser and editor for Python source. It provides a four-pane view of a Python file or folder world:

1. **Modules** selects a Python file.
2. **Scopes** selects `-- module --`, a class, or a nested class.
3. **Categories** organizes Members using inferred groups or `# category:` metadata.
4. **Members** selects a function, method, property, assignment, import block, documentation block, or executable statement.

The source editor works on the selected Member while validating the complete Python module before saving. PyBrowser preserves encoding, newline style, unrelated source text, and file permissions. Writes are atomic and guarded by modification time, size, and SHA-256 conflict detection.

## Design choices

### Member terminology

**Member** is the generic term throughout the interface for anything editable in the Members pane. A Member may be a method, function, property, assignment, import group, documentation block, or executable statement.

### Source-owned categories

Categories are represented by comments next to Python definitions:

```python
# category: lifecycle
def start(self):
    pass
```

There is no separate category database. A category is created when its first Member is added or moved into it. Built-in inferred categories use Smalltalk-style names:

```text
-- imports --
-- constants --
-- docs --
-- functions --
-- variables --
as yet unclassified
```

### Safe structural editing

Structural commands create a complete in-memory candidate, parse it with LibCST, validate it with Python's AST parser, check for external file changes, and then write atomically. Category metadata is not shown as part of a Member's editable source.

### Shared workspace

Browser, File View, Implementers, and Senders windows share one workspace. A save in one window invalidates and reparses the changed module in other windows. New definitions become available to quick navigation and source-model queries after indexing completes.

### Responsive indexing

Folder worlds are indexed through `QThreadPool` workers. Implementers, Senders, Find in World, and type checking also run outside the Qt UI thread. The Source Model activity strip reports current work and progress.

## Installation

Python 3.14 is the target runtime.

```powershell
py -3.14 -m pip install -e .[dev]
py -3.14 -m pybrowser
```

Open a file directly:

```powershell
py -3.14 -m pybrowser C:\path\to\app.py
```

Run tests:

```powershell
py -3.14 -m pytest
```

Optional type checking:

```powershell
py -3.14 -m pip install basedpyright
```

## Browsing and editing

- Open a Python file or a folder world.
- Select a module, scope, category, and Member.
- Edit the Member in the source pane.
- A changed Member becomes bold and bright yellow.
- Save with `Ctrl+S` or abandon with `Ctrl+L`.
- Navigation is blocked until pending Member edits are saved or explicitly abandoned.

Right-click menus expose context-appropriate operations, including View in File, New Class, New Method, Move Member to Category, Delete Member, Implementers, and Senders. Members can also be dragged onto an existing category.

## Windows

PyBrowser windows are independent top-level windows and can be arranged side by side.

The **Window** menu uses the `Alt+W` accelerator and lists windows in opening order. Entries are numbered. While the Window menu is open, press `1` through `9` to activate the corresponding window. Standard Up, Down, Left, Right, Enter, and Space menu navigation is supported.

`Ctrl+W` closes the focused window. Closing the last Browser window asks whether to quit PyBrowser. `Ctrl+Q` requests a safe application-wide quit. Console `Ctrl+C` follows the same normal close path so unsaved edits retain their safeguards.

## Hotkeys

### Files, windows, and saving

| Shortcut | Action |
|---|---|
| `Ctrl+O` | Open Python file |
| `Ctrl+Shift+O` | Open folder world |
| `Ctrl+S` | Save the current Member or editable view |
| `Ctrl+L` | Abandon changes in the current Member or editable view |
| `Ctrl+W` | Close the focused window |
| `Ctrl+Q` | Quit PyBrowser safely |
| `Ctrl+Shift+B` | Open a new Browser on the shared world |
| `Alt+W` | Open the Window menu |
| `1` to `9` in Window menu | Activate the numbered window |
| `Ctrl+C` in console | Request safe application shutdown |

### Navigation and search

| Shortcut | Action |
|---|---|
| `Ctrl+P` | Quick-open module |
| `Ctrl+T` | Quick-open indexed symbol or Member |
| `Ctrl+B` | Open a new Browser on the selected class name |
| `Ctrl+Shift+F` | Find text throughout the world |
| `Ctrl+F` | Focus the always-visible Find field |
| `Enter` in Find field | Execute Find |
| `Ctrl+G` | Find next |
| `Ctrl+Alt+G` | Go to source line |
| `Alt+Left` | Navigate backward |
| `Alt+Right` | Navigate forward |

### Source editor

| Shortcut | Action |
|---|---|
| `Ctrl+H` | Replace in current Member |
| `Ctrl+/` | Toggle comments |
| `Tab` | Indent selection or advance to next tab stop |
| `Shift+Tab` | Unindent selection |
| `Enter` | Smart newline and indentation |

### Tools

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+T` | Run BasedPyright or Pyright type checking |

## Structural commands

The **Structure** menu and context menus support:

- New Function
- New Class
- New Method
- Rename Category
- Move Member to Category
- Duplicate Member
- Delete Member
- Convert method kind between instance, static, class, and property forms
- Create package `__init__.py`

## Implementers and Senders

Right-click a callable Member to search for Implementers or Senders. Query windows are modeless and editable. They support:

- `Ctrl+S` to validate and save the selected Member
- `Ctrl+L` to abandon changes
- `Ctrl+W` to close the query window
- `Ctrl+B` to browse a selected class

Sender analysis is lexical. Calls such as `run()`, `self.run()`, `worker.run()`, and `ClassName.run()` count as senders of `run` even when runtime type inference is unavailable.

## File View

**View in file...** opens an editable whole-module window positioned near the selected Module, Scope, Category, or Member. File View is intended for cleanup and edits that span structural boundaries. Saving validates and reparses the complete module, then refreshes the shared workspace.

## Preferences

**Edit > Preferences** controls:

- Code font and size
- Tab width
- Visible whitespace
- Dark or light theme

Preferences and main-window geometry are stored using `QSettings`.

## Type checking

**Tools > Run Type Check** invokes BasedPyright or Pyright with JSON output. Diagnostics appear in a navigable panel with severity, location, rule, and message. Type checking is optional and does not affect core browsing or editing.

## Current limitations

- Sender analysis is lexical rather than full runtime type inference.
- Method-kind conversion currently requires a single-line signature.
- Categories exist only when at least one Member carries category metadata or qualifies for an inferred category.
- PySide6 UI tests require a Qt-capable test environment; non-UI parser and structural tests run independently.
