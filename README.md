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
- Dedent Member editor
- Recent completed recovery transactions
- Minimum recovery retention days
- Recovery storage limit in MB
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


### Revision 11.9 implicit module globals and indentation design

Native semantic analysis now recognizes the names supplied by Python's module execution environment: `__name__`, `__file__`, `__cached__`, `__package__`, `__loader__`, `__spec__`, `__builtins__`, `__annotations__`, `__doc__`, and the built-in constant `__debug__`. These names are valid when referenced from functions as module globals and no longer produce `possibly-undefined-local` hints. Special method names such as `__repr__` and `__add__` are definitions or attributes rather than automatically bound bare globals, so arbitrary dunder spellings are not globally suppressed.

`INDENTATION_PLAN.md` specifies a reversible Member-editor projection that displays class and nested-class Members at column zero, records the exact source prefix, reapplies it before full-module validation, and leaves File View literal and unchanged. The plan intentionally precedes implementation because indentation projection touches the save boundary and requires round-trip coverage for tabs, decorators, nested classes, multiline strings, CRLF, encodings, and external-change protection.


#### Revision 11.10 reversible Member dedentation

The Browser Member editor and editable query windows now display class and nested-class Members at column zero through a reversible `MemberProjection`. PyBrowser records the exact source prefix, removes only that prefix from each non-empty displayed line, and reapplies it before the existing full-module LibCST/AST validation and atomic save. Module-level Members remain unchanged because their prefix is empty. Decorators, async definitions, multiline signatures, nested functions, continuation indentation, tabs, CRLF, blank lines, encoding, and unrelated source remain intact.

**Edit > Preferences > Dedent Member editor** controls the behavior and defaults on. A Member whose non-empty lines do not share the exact structural prefix is treated as unsafe and shown literally rather than guessed. File View remains a literal whole-file editor and is never projected.


## Revision 12.0 recovery journal

Every source write now creates a durable recovery transaction in the platform user-data directory. Member saves, File View saves, query-window saves, structural edits, and package `__init__.py` creation capture full before and after snapshots plus a JSON manifest that progresses through `prepared`, `committing`, and `committed`. The manifest records hashes, encoding, newline mode, file permissions, operation name, description, World root, and Browser location where available.

**File > Structural History...** (`Ctrl+Shift+H`) opens a modeless history window with newest-first transactions, status, disk-state comparison, hashes, a unified diff, pin/unpin controls, and **Restore Before As...** / **Restore After As...**. Opening a World scans for interrupted `prepared` or `committing` transactions and offers to open Structural History. Preferences control transaction count, minimum retention days, and maximum storage in MB. Pinned and incomplete transactions are never pruned automatically.

Image-style deferred disk commits are documented in `UNDO_PLAN.md` but intentionally deferred until a World overlay and consolidated `SourceWriteService` exist. Immediate writes remain the only mode in Revision 12.0.


## Revision 12.1 SQLite recovery index

Recovery metadata is now indexed in `journal.sqlite3` per World. SQLite is authoritative for Structural History ordering, status queries, incomplete-transaction scans, pinning, retention bookkeeping, and affected-file lookup. Full before/after source snapshots and `manifest.json` remain ordinary files so every transaction retains a portable recovery record.

The database enables `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `synchronous=FULL`, and `busy_timeout=5000`. Tables separate transactions from affected files and include indexes for timestamp, status, disk-commit state, and absolute path. Opening a World imports existing Revision 12.0 JSON transactions into SQLite, reconciles database rows with manifests, and marks entries damaged when snapshot files are absent. The schema includes `committed_to_disk` for the later image-style staged-commit overlay, but Revision 12.1 continues writing through to disk immediately.


## Revision 12.2 safe Structural Undo and Redo

Workspace-level **Undo Structural Change** (`Ctrl+Alt+Z`) and **Redo Structural Change** (`Ctrl+Alt+Y`) now restore journal snapshots only when every affected file matches the transaction's expected SHA-256. A mismatch blocks the operation without writing and directs the user to Structural History for comparison, Restore As, or File View. Browser, File View, Implementers, and Senders windows with unsaved edits in an affected file also block the operation and are activated for resolution.

Transactions progress from `committed` or `redone` to `undone`, and from `undone` to `redone`. SQLite and `manifest.json` both persist `undone_at` and `redone_at`. Structural History now provides **Undo Selected**, **Redo Selected**, **Open File View**, and eligibility-aware controls. Successful restoration preserves file modes, uses sibling temporary files and `os.replace()`, rolls back already-restored files if a later file fails, broadcasts every affected path to all workspace windows, refreshes semantic indexes, and restores the recorded Browser location. Undoing creation of a package `__init__.py` removes the file; redo recreates it.


## Revision 12.3 shared write service

`SourceWriteService` is now the single source-write authority. Browser Member saves, structural commands, File View, editable Implementers/Senders/reference windows, and package `__init__.py` creation submit `SaveRequest` objects through the Workspace service. The service validates the full module, checks the loaded document signature, prepares and finalizes the recovery transaction, performs an `fsync()` plus `os.replace()` atomic write, reparses the stored module, returns a `SaveResult`, and broadcasts the changed path exactly once.

UI windows retain presentation responsibilities such as projection reconstruction, selection restoration, cursor restoration, and error dialogs. They no longer directly coordinate journaling and disk replacement. This creates the stable boundary needed by the future journal-only staging overlay and **Commit Changes...** workflow.


### Revision 12.4 shared write service completion

Revision 12C is now complete. Legacy `journaled_atomic_write`, `journaled_create_file`, and direct `atomic_write` application paths were removed, along with the obsolete disk-writing `structural.create_package_init()` helper. Recovery and I/O tests now exercise the same `SourceWriteService` used by the GUI. `RecoveryJournal.update_prepared()` provides a public journal boundary for file-creation metadata, so the write service no longer imports private recovery functions or calls private SQLite upsert methods.


### Revision 12.5 journal hardening

Revision 12.5 hardens the complete 12A to 12C source-integrity stack. Redo now follows `undone_at` stack order, new commits supersede abandoned redo branches, snapshots are explicitly flushed with `fsync()`, SQLite uses schema `user_version = 3`, and journal/undo methods are normal `RecoveryJournal` methods rather than runtime monkey patches. Source replacement failures remain `failed`, while reparse or notification failures after a successful commit retain `committed` and record `post_commit_error`. GUI save paths consistently catch authoritative `SourceConflictError` results and no longer offer stale-document overwrite. Startup recovery transactions can be finalized, aborted, or marked reviewed according to their disk hash state, and retention covers terminal states while preserving pinned and incomplete transactions.


#### Revision 12.6 final 12A-12C hardening

Revision 12.6 adds explicit SQLite schema 1-to-2 and 2-to-3 migrations, including safe creation of the undone-at index only after its column exists and rejection of journals newer than the supported schema. Restart reconciliation now treats a missing after snapshot as normal for prepared, committing, aborted, and pre-replacement failed transactions. If disk matches the intended after hash, Finalize Transaction reconstructs the missing after snapshot durably before recording the recovered commit. Structural History exposes Mark Not Applied, Finalize Transaction, and Mark Reviewed with state-aware enablement.

New commits are persisted as committed before outstanding redo branches are superseded. Journal state transitions use BEGIN IMMEDIATE and expected-state checks, active undo/redo transactions are protected from retention, and ordinary write/rollback handling catches Exception rather than BaseException. Post-commit notification failures now return a successful SaveResult with warnings and a refreshed Document, allowing the writing editor to clear its dirty state while reporting the warning.


###### Revision 12.7 authoritative recovery mirrors and post-commit maintenance

SQLite is now unequivocally authoritative when a database row and portable manifest disagree. Startup reconciliation imports JSON only for transactions absent from SQLite; otherwise it repairs stale or missing manifest.json from the database and reevaluates snapshot damage. Core commit completion is separated from redo cleanup, retention, and history notification, so those post-commit maintenance failures return warnings without making a committed save appear uncertain. A reparse failure retains the validated committed candidate and current disk signature in a fallback Document, clears editor dirty state through the normal SaveResult path, and records the warning for Structural History. Retention protects incomplete and pinned transactions, the active undo/redo candidates, all reachable redo entries, and the configured newest committed history while allowing older eligible history to satisfy limits.


### Revision 12.8 structural command and recovery consistency fixes

Revision 12.8 restores all Browser structural commands by removing the obsolete UI-side validate and changed checks and routing validation and conflict detection exclusively through SourceWriteService. Duplicate Member now selects the inserted occurrence, selects its Python identifier for immediate renaming, and records separate duplicate_member and save_member transactions. Structural commands handle SourceConflictError, SourcePostCommitError, and SaveResult warnings. Recovery schema 4 persists recovered_at, reviewed_at, and superseded_at; reconstructed JSON uses the portable manifest shape; SQLite-first metadata transitions are used for pinning, status changes, and redo supersession. Undo and redo claim undoing/redoing states before replacing source files, and retention claims pruning rows before directory deletion. Ruff F821 is included in development checks to prevent undefined-name regressions.


#### Revision 12.9 transient recovery and stable write conflicts

Revision 12.9 recovers interrupted undoing, redoing, and pruning states after restart. Structural History can safely roll back or finalize claimed undo/redo transitions according to current file hashes, while ambiguous mixed states require review. Pending deletion records prevent reconciliation from recreating successfully pruned transaction directories. SourceWriteService now obtains one stable byte image and signature for conflict detection and journaling, and new-file creation uses O_EXCL no-replace semantics. Status changes merge from the current authoritative SQLite row, multiple post-commit warnings are retained, and recovery preference documentation is complete.


#### Revision 12.10 final document-load and recovery-authority hardening

Document loading now derives decoded text, scopes, and file signature from one stable byte image. Existing-file saves use a cooperative per-path lock plus a final expected-signature check immediately before replacement. Pinning and established journal transitions rebuild portable JSON from authoritative SQLite state. Interrupted undo and redo transactions require complete after snapshots, damaged automatic recovery actions are disabled, and recovery controls use direction-specific labels. PySide6 offscreen regression tests cover duplicate-member selection and rename behavior.


#### Revision 12.11 duplicate selection and Qt teardown safety

Duplicate Member now resolves the requested callable occurrence after reload and explicitly opens that row before selecting its identifier. Workspace window destruction no longer captures a deleted Python wrapper, and Window-menu rebuild callbacks disconnect when their owning window is destroyed. Qt object validity guards prevent late shutdown signals from touching deleted QMenu objects.


#### Revision 12.12 watcher-stable duplicate occurrence selection

Duplicate Member selection is now applied through one signal-blocked occurrence-selection helper that updates the list row, Member model, projection, and editor together. QFileSystemWatcher reloads preserve the current Member row as a fallback, so an ambiguous duplicate label cannot reset the Browser to the first occurrence after the write completes.
