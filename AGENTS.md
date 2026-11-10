# AGENTS.md

This file provides development context for AI coding agents working on PyBrowser. Read this file, `README.md`, `UNDO_PLAN.md`, and `INDENTATION_PLAN.md` before changing source mutation, Browser restoration, recovery history, or Qt window lifecycle code.

## Product intent

PyBrowser is a Smalltalk-inspired structural browser for ordinary Python source. The product priority is not to imitate an IDE cosmetically. The priority is to make Python source navigable and editable as Modules, Scopes, Categories, and Members while preserving exact source bytes outside the selected edit.

The user values:

- Structural navigation over file-only navigation
- Fast keyboard workflows
- Modeless, independent top-level windows that can be arranged side by side
- Conservative source safety
- Visible, actionable diagnostics
- Explicit Git operations
- Auto-Commit writes immediately; Manual Commit durably stages through the World overlay
- A future Smalltalk-style staged image workflow built correctly through a World overlay

Use **Member** as the generic UI term. A Member can be a function, method, property, assignment, import block, documentation block, or executable statement.

## Runtime and platform

- Target runtime: Python 3.14
- GUI: PySide6
- Structural parsing: LibCST plus Python AST validation
- Primary development platform: Windows
- Tests must continue to support non-GUI environments where PySide6 tests are skipped
- Windows process spawning requires guarded entry points and `freeze_support()`

## Core architecture

### Parser and model

- `pybrowser/model.py` defines immutable source structures and `Document`.
- `pybrowser/parser.py` creates structural scopes and Members.
- `read_document()` must derive text, scopes, encoding, newline mode, and signature from one stable byte image.
- Member spans exclude `# category:` metadata so category comments do not appear in Member editor text.
- `Span` offsets are indexes into literal `Document.text`, including CR characters in CRLF files. Never compare them with offsets from `Path.read_text()`, which may perform universal-newline translation.

### Browser restoration

Browser selection identity is not merely a label. Duplicate definitions can have identical labels. Restoration must preserve:

- Module path
- Scope
- Category
- Member label
- Source-order row
- Preferably source span start when available

When several Members share a label, a valid saved `fallback_row` that matches the label must win over the first label match.

Do not rely solely on Qt selection signals to synchronize internal state. Internal restoration should use signal blockers and update `self.member`, the Member list, projection, and editor together.

### Member projection

Only Member editors use reversible dedentation. File View is always literal.

Never use unrestricted `textwrap.dedent()`. Record and remove only the exact common indentation prefix. Reapply that exact prefix to non-empty lines before reconstructing the module.

### Shared writes

`SourceWriteService` is the only supported application source-write boundary. UI code must not call low-level atomic-write or journal helpers directly.

A save must preserve this sequence:

1. Build a complete candidate module.
2. Validate with LibCST and `compile(..., ast.PyCF_ONLY_AST)`.
3. Acquire the cooperative path lock.
4. Perform a stable read and compare against the loaded `Document.signature`.
5. Prepare the recovery transaction and before snapshot.
6. Write and flush a sibling temporary file.
7. Recheck the expected signature immediately before `os.replace()`.
8. Replace atomically.
9. Finalize the recovery transaction and after snapshot.
10. Reparse and notify the Workspace exactly once.

New-file creation must use exclusive no-replace behavior. Never replace a file that appeared after the operation began.

### Recovery journal

- SQLite is authoritative for metadata.
- `manifest.json` is a portable mirror.
- Complete before and after snapshots are ordinary files.
- Established transaction transitions should update SQLite first and then rebuild JSON from the authoritative row.
- Do not let stale JSON reactivate redo state or overwrite pinning and warning metadata.
- Do not prune pinned, incomplete, active undo, or active redo transactions.
- Interrupted `prepared`, `committing`, `undoing`, `redoing`, and `pruning` states require explicit restart handling.
- Automatic undo, redo, abort, and finalize operations require exact hash matches.
- Never add a casual force-overwrite action.

### Workspace

All windows for a World share one `Workspace`.

The Workspace owns:

- Current World
- Recovery journal
- Shared write service
- Window registry
- Cross-window file-change notifications
- Structural undo and redo coordination

A writer ignores its own synchronous file-change broadcast because it already performs precise reparse and restoration. Other windows refresh only when they have no unsaved conflicting edits.

### Indexing

Folder indexing uses `ProcessPoolExecutor` under a Qt worker. Keep worker entry points free of Qt object dependencies.

Do not catch `BaseException` around worker results. `KeyboardInterrupt`, `SystemExit`, and other process-level exceptions should not be converted into ordinary diagnostics.

GUI unit tests should disable process-pool indexing unless indexing itself is the subject of the test. Spawned Windows workers can otherwise keep pytest alive after a test window is closed.
- Existing-module content changes must not publish a World/module-set change, rebuild the Modules tree, restart full-World indexing, or run full module discovery on the Qt thread.
- QFileSystemWatcher directory events must be coalesced and scanned in a background QRunnable. Known Workspace writes must suppress their duplicate watcher events without suppressing later external edits.
- Physical index-cache checks use cheap mtime/size stamps. SHA-256 remains mandatory at source-write, staging, conflict, snapshot, and recovery boundaries.
- A full-index result for a path changed since that full run began must be ignored in favor of the newer single-module result.

### Qt lifecycle

Qt object lifetime is a high-risk area on Windows.

- Do not capture a window wrapper in a `destroyed` lambda.
- Disconnect Workspace callbacks when the owning window is destroyed.
- Use `shiboken6.isValid()` before touching Qt objects from callbacks that can outlive their owner.
- Suppress nonessential window-registry emissions while `QCoreApplication.closingDown()` is true.
- Tests must explicitly unregister, close, schedule deletion, and process posted events.
- Modal dialogs in GUI tests should be monkeypatched to fail immediately rather than hang headless pytest. Patch both QMessageBox convenience methods and instance `exec()`.
- GUI tests must explicitly set and restore the global `source/writeMode` QSettings value; a developer Manual Commit preference must not change test semantics.

## UI priorities

- Keep the four-pane Browser responsive.
- Preserve selection and cursor across save, refresh, watcher events, and structural operations.
- Unsaved state must be obvious and must block destructive navigation.
- Duplicate definitions remain visible and diagnostically marked.
- Duplicate Member should select the inserted occurrence and select its identifier for immediate rename. A later general module reload preserves structural identity but is not required to preserve an ephemeral QTextCursor selection.
- File View is the escape hatch for edits spanning structural boundaries.
- Browser, File View, query, and history windows remain independent top-level windows.
- Keyboard behavior is a first-class feature.

## Testing requirements

Before delivery, run:

```powershell
py -3.14 -m pytest -q
py -3.14 -m ruff check pybrowser --select F821
```

For focused Qt behavior on Windows:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
py -3.14 -m pytest tests/test_structural_gui.py -q
```

GUI tests must:

- Disable unrelated process-pool indexing and file watchers
- Fail on unexpected modal dialogs
- Avoid open-ended waits
- Clean up windows in `finally`
- Process deferred deletion events
- Verify behavior, not merely source-code strings

Critical regression scenarios include:

- Duplicate then rename changes only the inserted method
- Ambiguous duplicate-label restoration preserves source occurrence
- Save rejects external changes before journaling
- Final pre-replacement signature change is rejected
- New-file creation never overwrites a concurrently created target
- SQLite repairs stale JSON
- Multiple undo and redo order
- Redo branch supersession
- Interrupted save, undo, redo, and prune recovery
- Qt window shutdown without deleted-object callbacks

## Coding and delivery conventions

- Prefer explicit dataclasses and enums at integrity boundaries.
- Keep portable manifest fields distinct from SQLite implementation fields.
- Preserve encoding, newline style, final newline, file mode, and unrelated source.
- Recovery hashes and snapshot assertions operate on exact bytes. On Windows, never use `Path.write_text()` or `Path.read_text()` to prepare or verify hash-sensitive fixtures because newline translation can change LF to CRLF.
- Source-inspection tests must pass `encoding="utf-8"` to `Path.read_text()` so Windows active-code-page settings cannot break Unicode source.
- Avoid broad exception handling around source-integrity operations.
- Keep UI presentation separate from journal and disk coordination.
- Do not introduce a second write path for tests.
- Version each delivered ZIP consistently in `pyproject.toml` and `pybrowser/__init__.py`.
- Git check-in examples must be one line with a semicolon:

```bash
git add pyproject.toml requirements.txt README.md AGENTS.md UNDO_PLAN.md pybrowser tests; git ci -m "Message"
```

## Planned direction

### Stage 12D

Add Git context and real multi-file transactions:

- Repository root, branch, and HEAD metadata
- Tracked, modified, staged, and untracked state per changed file
- One transaction spanning multiple validated candidates
- Partial-commit recovery and rollback
- Explicit suggested Git commands only

### Stage 12E

Add journal-only staging through a World overlay:

- Every reader sees staged source instead of stale disk
- Commit All Changes
- Selective Commit Changes
- Retain, commit, or discard prompts on quit and World switching
- Indexing, queries, type checking, and future runtime processes consume overlay content

Do not implement staging by merely skipping `os.replace()`. Without the overlay, different parts of the application would read inconsistent source.
