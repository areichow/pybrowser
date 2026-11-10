# PyBrowser

PyBrowser is a desktop structural browser and editor for Python source code. Its interface is inspired by Smalltalk browsers: instead of treating a project as a collection of large text files, PyBrowser lets you navigate a **World** through Modules, Scopes, Categories, and Members.

PyBrowser is intended for developers who want fast structural navigation while retaining ordinary Python files, familiar editors, and explicit control over source changes. It does not introduce a proprietary project format.

## What PyBrowser does

The main Browser has four structural panes:

1. **Modules** lists Python files in the open World.
2. **Scopes** lists the module scope, classes, and nested classes.
3. **Categories** groups source Members using inferred categories and optional `# category:` comments.
4. **Members** lists functions, methods, properties, assignments, import groups, documentation blocks, and executable statements.

Selecting a Member opens only that source construct in the editor. PyBrowser validates the entire reconstructed module before saving.

Additional windows provide:

- **File View** for literal whole-file editing.
- **Implementers** and **Senders** searches.
- **References** from the native semantic index.
- **Diagnostics** from native analysis and optional BasedPyright or Pyright runs.
- **Structural History** with durable before and after snapshots, safe undo and redo, crash recovery, pinning, and snapshot export.

## Requirements and installation

PyBrowser currently targets **Python 3.14** and **PySide6 6.8 or newer**.

```powershell
py -3.14 -m pip install -e .[dev]
py -3.14 -m pybrowser
```

Open a file directly:

```powershell
py -3.14 -m pybrowser C:\path\to\app.py
```

Run the test suite:

```powershell
py -3.14 -m pytest -q
```

Run the focused offscreen GUI regression test:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
py -3.14 -m pytest tests/test_structural_gui.py -q
```

Run static undefined-name checking:

```powershell
py -3.14 -m ruff check pybrowser --select F821
```

## Basic workflow

1. Open a Python file or a folder World.
2. Select a Module, Scope, Category, and Member.
3. Edit the Member in the source editor.
4. Save with **Ctrl+S**, or abandon pending edits with **Ctrl+L**.
5. Use **File > Structural History** or **Ctrl+Shift+H** to inspect saved transactions.
6. Use **Ctrl+Alt+Z** and **Ctrl+Alt+Y** for safe structural undo and redo.

Navigation is blocked while the current Member has unsaved edits unless those edits are explicitly abandoned.

## Structural editing

The Structure menu and context menus support:

- New Function
- New Class
- New Method
- Rename Category
- Move Member to Category
- Duplicate Member
- Delete Member
- Convert method kind between instance, static, class, and property forms
- Create package `__init__.py`

After **Duplicate Member**, PyBrowser selects the inserted source occurrence and selects its identifier so it can be renamed immediately.

## Source-owned categories

Categories are ordinary comments stored with the source:

```python
# category: lifecycle
def start(self):
    pass
```

There is no separate category database. Inferred categories include imports, constants, documentation, functions, variables, class variables, and executable code.

## Member editor projection

Class and nested-class Members may be displayed at column zero through a reversible projection. PyBrowser records the exact tabs or spaces used by the original source and reapplies that prefix before reconstructing the module.

The **Dedent Member editor** preference controls this behavior. File View always displays literal source and never applies the projection.

## Safe writes and recovery

All source mutations pass through one `SourceWriteService`. The service:

1. Validates the complete candidate with LibCST and Python's AST parser.
2. Uses a stable byte read and SHA-256 signature to detect external changes.
3. Acquires a shared cooperative per-path PyBrowser lock used by saves, file creation, undo, and redo.
4. Writes durable recovery metadata and a complete before snapshot.
5. Performs a final signature check immediately before atomic replacement.
6. Flushes source and snapshot data with `fsync()` where supported.
7. Reparses the committed source and notifies every window in the shared Workspace.

Recovery metadata is indexed in SQLite. Portable JSON manifests and complete before and after source snapshots remain on disk. SQLite is authoritative when the two representations disagree.

Automatic undo and redo require the current file hash to match the expected transaction hash. PyBrowser does not offer a casual force-overwrite operation.

## Shared Workspace and background indexing

Browser, File View, query, and history windows share a Workspace. Saves invalidate cached information and refresh other windows that do not contain unsaved edits.

Folder Worlds are indexed in child Python processes through `ProcessPoolExecutor`. Results return to the Qt UI thread in batches. The first selected file remains usable while the rest of the World is indexed.

## Native semantic analysis

PyBrowser uses Python's `ast` and `symtable` modules to build a native source model. It records symbols and references for modules, classes, functions, methods, parameters, imports, assignments, reads, writes, calls, decorators, annotations, bases, and deletes.

Native diagnostics currently include:

- Duplicate definitions in one scope
- Possibly undefined local names
- Unused category metadata
- Duplicate category directives

Optional BasedPyright or Pyright checking is available through **Tools > Run Type Check**.

## Useful shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+O | Open Python file |
| Ctrl+Shift+O | Open folder World |
| Ctrl+S | Save current Member or editable view |
| Ctrl+L | Abandon pending edits |
| Ctrl+W | Close focused window |
| Ctrl+Q | Quit safely |
| Ctrl+P | Quick-open Module |
| Ctrl+T | Quick-open symbol |
| Ctrl+B | Browse selected class |
| Ctrl+F | Find in current view |
| Ctrl+Shift+F | Find in World |
| Shift+F12 | Find references |
| Ctrl+Shift+H | Structural History |
| Ctrl+Alt+Z | Undo structural/source transaction |
| Ctrl+Alt+Y | Redo structural/source transaction |
| Ctrl+Shift+T | Run type checker |

## Architectural choices

### Ordinary Python remains the source of truth

PyBrowser edits normal `.py` files. Categories are comments, and recovery data is separate from the project source.

### Members are projections, not independent files

A Member edit is reconstructed into the original module. The entire candidate module must parse before PyBrowser writes anything.

### Immediate write-through is the current mode

**File > Auto-Commit Enabled** is checked by default and preserves immediate write-through behavior. Clear the checkbox to use Manual Commit mode. In Manual Commit mode, Ctrl+S and structural operations durably stage complete validated source snapshots in the recovery journal while physical files remain unchanged. Staged source is restored after restart and is visible to Browsers, File View, queries, search, references, and native indexing.

Use **File > Commit Changes to Disk** to atomically validate physical baselines and write every active staged file. **View Staged Changes** opens a dedicated modeless review window with per-file baseline-to-staged diffs, existing-versus-virtual status, external-conflict detection, unsaved-window protection, Commit Selected, Abandon Selected, Open Staged Source, Commit All, and Abandon All. **Abandon Staged Changes** retains recovery history while restoring the visible World to physical disk. Quit and World switching offer Commit Changes, Abandon Changes, View Changes, and Cancel. Type checking is deliberately disabled while staged changes exist until overlay mirror materialization is implemented.

### Git remains explicit

PyBrowser history is an immediate recovery and structural-undo system. It is not a replacement for Git. Planned Git integration will add context and suggested commands, but PyBrowser will not automatically commit, reset, stash, checkout, or amend a repository.

### Conservative conflict handling

When disk state does not match the expected hash, PyBrowser refuses automatic replacement. Structural History and File View provide inspection and recovery paths.

## Current limitations

- Sender analysis is lexical and does not provide full runtime type inference.
- Method-kind conversion currently requires a single-line signature.
- Categories only exist when a Member supplies metadata or qualifies for an inferred category.
- Structural undo and redo currently operate on transactions whose file states match exact hashes.
- Staged Commit Selected and Commit All use durable commit batches with per-file pending, replacing, replaced, and rolled-back progress. Restart recovery classifies all-before, all-after, mixed, and foreign disk states and offers complete-forward, complete-rollback, or manual review.
- Durable staging, atomic Commit All, and per-file Commit Selected are implemented. Staged deletion, rename/move, and type-check mirror materialization remain planned.
- PySide6 GUI tests require a Qt-capable environment. The offscreen platform is recommended for CI.
- Shared path locks coordinate PyBrowser saves, creation, undo, and redo, but cannot prevent an unrelated program from modifying a file at the exact instant of replacement. A final stable signature check reduces this window.

## Roadmap

- **12A** Recovery Journal
- **12B** Structural Undo and Redo
- **12C** Shared Write Service
- **12D.0** Overlay-capable Source and Multi-file Disk Commit
- **12E** Auto/Manual Commit and Journal-only Staging Overlay
- **12D.1** Git Context and Git-oriented History

Detailed recovery design and transaction semantics are documented in `UNDO_PLAN.md`. Member indentation projection is documented in `INDENTATION_PLAN.md`.


## Source span convention

Member spans are offsets into the literal decoded `Document.text`. For CRLF files, carriage returns count toward those offsets. Code and tests must not compare a Member span with offsets obtained from `Path.read_text()`, because Python may translate CRLF to LF while reading. The reversible Member projection handles structural indentation separately for editor display.
