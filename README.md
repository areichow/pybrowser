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
| `Shift+F12` | Find references to the selected name |

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

## Native semantic intelligence

PyBrowser builds a native semantic model during background indexing using Python's `ast` and `symtable` modules. The model records:

- Module, class, function, method, parameter, import, and assignment symbols
- Reads, writes, calls, imports, class bases, decorators, annotations, and deletes
- Source path, lexical scope, line, and column for each symbol and reference

Right-click a Member or identifier and choose **References to...**. Member context menus can filter references to reads, assignments, or imports. `Shift+F12` finds all reference kinds for the identifier under the cursor.

Native PyBrowser diagnostics report:

- Duplicate class, function, and method definitions in one scope
- Possibly undefined local names
- Unused or orphaned `# category:` metadata
- Duplicate category directives before a Member

Native rules appear in the Diagnostics panel with a `PYBROWSER:` prefix and do not require BasedPyright, Pyright, Node.js, or an LSP server.

## Structural undo plan

The package includes `UNDO_PLAN.md`, which specifies a Smalltalk-style Member version journal, safe workspace undo/redo, crash recovery, retention, and optional Git context. The plan deliberately keeps Git operations explicit and treats PyBrowser history as immediate pre-commit recovery rather than a replacement for Git.

A full LSP client is deferred. The current design combines native AST/symbol-table intelligence with optional batch BasedPyright or Pyright diagnostics.

## Type checking

**Tools > Run Type Check** invokes BasedPyright or Pyright with JSON output. Diagnostics appear in a navigable panel with severity, location, rule, and message. Type checking is optional and does not affect core browsing or editing.

## Current limitations

- Sender analysis is lexical rather than full runtime type inference.
- Method-kind conversion currently requires a single-line signature.
- Categories exist only when at least one Member carries category metadata or qualifies for an inferred category.
- PySide6 UI tests require a Qt-capable test environment; non-UI parser and structural tests run independently.


## Revision 11.1 selection and duplicate-definition fixes

- Save and structural writes now clear the pending-edit state before rebuilding Browser panes, preventing abandon prompts during a successful save.
- Browser pane restoration is performed under signal blockers as one internal reload transaction.
- Renaming a Member preserves its source-order selection even though its label changes.
- Duplicating a Member keeps the original class and category selected and selects the newly inserted duplicate.
- Duplicate methods and functions in one scope are painted light red (`#dca8ac`) in the Members pane and include a duplicate-definition tooltip. Native semantic diagnostics continue to report the same condition.


## Revision 11.2 diagnostic visibility

Native diagnostic concerns are aggregated across the structural Browser. The highest severity controls the glyph and normal text color: `✕` error (`#f07178`), `▲` warning (`#dca8ac`), and `●` information (`#82aaff`). Multiple concerns append a count, such as `▲3`. Modules, Scopes, Categories, and Members carry these markers and detailed tooltips. The selected Member's breadcrumb includes its diagnostic marker and summary tooltip. The Source Model strip reports world totals for errors, warnings, and hints after indexing.

Unsaved Member state retains precedence: a changed Member remains bold bright yellow (`#ffd166`) while its diagnostic glyph stays in the displayed label and all concerns remain in the tooltip. Saving or abandoning restores the diagnostic severity color. Parse-error modules continue to use the error marker even when semantic indexing cannot complete.


## Revision 11.3 save-selection persistence

A save now preserves a full Browser bookmark: Module path, Scope, Category, Member label, Member row, and editor cursor position. Atomic file replacement can trigger both file and directory watcher events; delayed folder refreshes restore that bookmark instead of reopening the module at its first Member. Programmatic Module selection is performed under `QSignalBlocker`, so `currentItemChanged` cannot cause an unbookmarked second open. A Browser also ignores its own synchronous Workspace file-change broadcast because the writing Browser already performs the precise post-save reparse and restoration; other workspace windows continue to receive and process the broadcast. Renamed Members fall back to the same source-order row when the old label no longer exists.


## Revision 11.4 stable world switching and large-repository indexing

Opening a Recent World now cancels and invalidates the previous indexing generation before any Module-tree or watcher objects are replaced. The refresh timer is stopped, old filesystem watches are removed, semantic and index caches are cleared, and opening is guarded against re-entry. Stale result batches are discarded by generation before touching Qt items. This closes the race where an old indexing task could deliver results while a Recent Worlds action rebuilt the tree, a plausible cause of the native Windows crash dialog.

World indexing now uses up to four child Python processes through `ProcessPoolExecutor`. LibCST, AST, and symbol-table parsing therefore no longer hold the main Qt process's Python GIL while indexing large repositories such as Django. Results are returned to Qt in batches of 24 modules, Module-tree repainting is suspended for each batch, and module items are updated through a direct path-to-item map rather than an O(n) tree scan for every result. Progress updates occur once per batch rather than once per file. The first selected module is painted before child-process indexing starts.


## Revision 11.5 Recent Worlds native-menu crash fix

The Recent Worlds failure was traced to native menu lifetime, not folder parsing. Selecting a recent entry called `open_world_path()` directly from the QAction callback. `open_world_path()` called `_remember_world()`, which synchronously cleared and rebuilt the same Recent Worlds QMenu. On Windows this could delete the QAction while Qt was still dispatching that QAction, producing the native “Python has stopped working” termination rather than a Python traceback.

Recent-world activation is now two-stage. The QAction stores the path and schedules `_finish_open_recent_world()` with `QTimer.singleShot(0, ...)`, allowing the native menu callback to return before the world changes. Updating the MRU list is also queued, and `_rebuild_recent_menu()` refuses to clear the menu while it is visible. QAction paths are stored with `setData()` rather than captured only by a callback default.

The Windows process-indexing entry point is also protected with the standard `if __name__ == "__main__"` guard and `multiprocessing.freeze_support()`. This prevents `ProcessPoolExecutor` child startup from recursively launching another PyBrowser when invoked with `python -m pybrowser` or from a frozen Windows executable.


## Revision 11.6 lexical binding fixes

Native undefined-local analysis now recognizes Python bindings that are not represented as ordinary `ast.Name(Store)` nodes. Lambda expressions receive their own lexical scope, and positional-only, positional, keyword-only, variadic, and keyword parameters are registered before the lambda body is analyzed. Lambda defaults remain analyzed in the enclosing scope, matching Python evaluation rules.

Exception aliases from `except Exception as error:` are registered as local exception symbols and write references before the handler body is analyzed. Uses such as `print(error)` are therefore no longer reported as possibly undefined. Truly unresolved names inside lambda bodies and exception handlers continue to produce `PYBROWSER:possibly-undefined-local` information messages.


## Revision 11.7 module globals and File View search

Native semantic analysis now predeclares the complete module namespace before analyzing function and method bodies. Classes, functions, imports, and assignment targets defined later in the same file are valid globals and no longer produce `possibly-undefined-local` hints. This covers constructor calls such as `RepoLock(...)` before `class RepoLock`, calls to a later `diagnostic()` function, and calls from `diagnostic()` to a later `colorize()` function.

File View now provides `Ctrl+F` Find, `Ctrl+G` Find Next, `Ctrl+H` Replace, and `Ctrl+Shift+G` Go to Line. Find supports match case, whole-word matching, backward search, and wrap-around behavior. **Find All in Current File** opens a results panel below the editor with line, column, and source preview; selecting a result moves the File View editor to that match. Replace supports Replace and Replace All using the same literal, case, and whole-word rules.


## Revision 11.8 editor zoom, Member ordering, and drag clarity

Code editors now support `Ctrl+=` or `Ctrl++` to increase font size, `Ctrl+-` to decrease it, and `Ctrl+mouse wheel` to zoom. The range is 6 through 48 points, and the selected size is persisted in `QSettings` as the shared editor font size. This applies to the Browser code pane, File View, and editable query windows because all use the shared `Editor` widget.

The compact Find row now includes **Order: File / Sort**. **File** preserves source order. **Sort** presents the current Category's Members alphabetically using case-insensitive labels while retaining the underlying source locations and drag/drop identity. Changing order keeps the selected Member selected.

The synthetic `-- entire category --` Member has been removed. File View is now the supported way to inspect or edit multiple Members together, which avoids a second overlapping structural editing model and keeps Member lists limited to real source constructs.

During a Member drag, the Category under the pointer receives a bright blue `#2f78c4` background. The highlight follows the pointer and is cleared on drop or drag leave.
