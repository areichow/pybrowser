# Structural Undo and Recovery Plan

PyBrowser should provide Smalltalk-style source history while remaining compatible with Git. The design uses PyBrowser's own append-only recovery journal for every source write, then treats Git as a complementary project-history system rather than a prerequisite.

## Goals

- Preserve every saved Member version, including ordinary `Ctrl+S` saves.
- Record structural operations such as Move Member, Delete Member, Rename Category, New Class, and method-kind conversion as named transactions.
- Survive application crashes, power loss, and incomplete multi-file operations.
- Undo only when the current disk state still matches the transaction's expected hash.
- Refresh every Browser, File View, Implementers, and Senders window after undo or redo.
- Never require Git, but expose Git context when a world is a Git working tree.

## Layer 1: Editor undo

`Ctrl+Z` and `Ctrl+Y` remain local to the focused `QPlainTextEdit`. This handles unsaved typing and does not modify files or the workspace structural history.

## Layer 2: Durable source journal

Every successful source write creates a transaction before replacing the source file. The default storage location should be the platform user-data directory:

- Windows: `%LOCALAPPDATA%\PyBrowser\history\<world-id>\`
- Linux: `~/.local/share/pybrowser/history/<world-id>/`

An optional project-local location may be supported at `.pybrowser/history/`; PyBrowser should recommend adding that directory to `.gitignore`.

Each transaction directory contains:

```text
20261105-103155-0042/
    manifest.json
    before/
        package/module.py
    after/
        package/module.py
```

The JSON manifest records:

- Format version and transaction ID
- UTC timestamp and human-readable operation description
- Operation kind, such as `save_member`, `move_member`, or `delete_member`
- `prepared`, `committing`, or `committed` status
- Relative file paths
- Encoding, newline mode, permissions, before hash, and after hash
- Browser location before and after the operation
- Optional Git repository root, branch name, and current HEAD commit

Snapshots should initially be complete file copies rather than deltas. Python files are normally small, full snapshots are easy to inspect, and restoration does not depend on a chain of patches.

## Write transaction

1. Read every file that may change and calculate SHA-256 hashes.
2. Build and validate all candidate modules in memory.
3. Create the transaction directory and write all `before` snapshots.
4. Write and flush a manifest marked `prepared`.
5. Mark the manifest `committing`.
6. Write sibling temporary source files, flush them, preserve permissions, and replace originals with `os.replace()`.
7. Write `after` snapshots and mark the manifest `committed`.
8. Reparse changed modules, rebuild native semantic indexes, and notify the shared Workspace.
9. Add the transaction to the workspace undo stack.

A crash after step 3 remains recoverable because the original source is already journaled.

## Safe structural undo and redo

Workspace actions should use:

- `Ctrl+Alt+Z`: Undo the latest structural/source transaction
- `Ctrl+Alt+Y`: Redo the latest undone transaction

Before undo, every current file hash must equal the transaction's `after` hash. Before redo, every current file hash must equal its `before` hash. A mismatch blocks automatic replacement and offers:

- Compare current, before, and after versions
- Restore the snapshot to another path
- Open File View
- Cancel

The first implementation should not present a casual force-overwrite option.

Undo and redo are workspace-level. They must refuse to run while any affected Browser, File View, Implementers, or Senders window has unsaved edits.

## Structural History window

A modeless **Structural History** window should list transactions in newest-first order and show:

- Timestamp and operation description
- Changed files
- Committed, undone, incomplete, or conflicted status
- Before and after hashes
- Side-by-side or unified diff
- Browser location before and after
- Undo eligibility

Actions:

- Undo Selected
- Redo Selected
- Restore Before As...
- Restore After As...
- Open File View
- Pin Transaction

## Startup recovery

At startup, PyBrowser scans for manifests in `prepared` or `committing` state. It compares each current file with the recorded before and intended after hashes:

- Current equals before: the source commit probably did not begin.
- Current equals after: the source commit likely completed but journal finalization failed.
- Current equals neither: external changes occurred and manual review is required.

PyBrowser should present an inspection window and never resolve an ambiguous transaction silently.

## Retention

Initial defaults:

- Keep the newest 200 transactions per world.
- Keep transactions for at least 30 days.
- Limit completed history to 500 MB per world.
- Never automatically remove incomplete or pinned transactions.
- Delete oldest unpinned committed transactions first.

Repeated saves of one Member may later be grouped for display, but each physical write should remain independently crash-recoverable.

## Git integration

Git and PyBrowser history solve different problems:

- Git records intentional project commits, branches, and collaboration history.
- PyBrowser records immediate Member and structural changes before they are committed.

When a world is inside a Git repository, the transaction manifest should record:

- Repository root
- Current branch or detached-HEAD state
- HEAD commit hash
- Whether each changed file was tracked, modified, staged, or untracked before the operation

The Structural History window may offer:

- Show Git Diff
- Open Repository
- Copy suggested `git add` and commit command
- Identify the first PyBrowser transaction after a Git commit

PyBrowser should never automatically commit, reset, checkout, stash, or amend Git state. Git operations remain explicit user actions.

## Delivery sequence

### Revision A: recovery journal

- Journal every source write
- JSON manifests and full before/after snapshots
- Retention policy
- Startup detection of incomplete transactions
- Structural History window with Restore As

### Revision B: safe undo and redo

- Workspace undo/redo stack
- Hash preconditions
- `Ctrl+Alt+Z` and `Ctrl+Alt+Y`
- Cross-window conflict detection and refresh
- Browser location restoration

### Revision C: Git context and multi-file polish

- Git metadata in manifests
- Diff display
- Multi-file partial-commit recovery
- Pinned transactions
- Snapshot compression or content-addressed blobs if storage measurements justify it

A full LSP client remains a possible later feature, but it is intentionally deferred. Native AST/symbol-table analysis and optional batch BasedPyright/Pyright diagnostics remain the current semantic strategy.


### Deferred write / image-style commit mode

A future phase will add a preference choosing between **Write through immediately** and **Stage in journal until commit**. Staged mode requires a World overlay filesystem so every Browser, File View, semantic index, type check, query, and runtime launch reads the staged after-snapshot rather than stale disk content. Planned File commands are **Commit All Changes** and **Commit Changes...**, with the latter presenting a transaction/file summary and allowing selective commits. Quit and World switching must prompt to commit, retain staged changes, or discard them. This is intentionally deferred until the shared `SourceWriteService` and virtual World overlay are implemented; merely skipping `os.replace()` in the current architecture would cause indexers and other windows to read inconsistent source.


### Revision 12.1 SQLite journal index

`journal.sqlite3` is now the authoritative metadata index while complete source snapshots and portable per-transaction `manifest.json` files remain on the filesystem. The database uses foreign keys, WAL mode, `synchronous=FULL`, and a 5000 ms busy timeout. On World open, PyBrowser imports Revision 12.0 JSON-only transactions, reconciles rows with transaction directories, and marks transactions damaged when required snapshot files are missing. This schema includes `committed_to_disk` so the future staged overlay can query pending changes without another metadata migration.


#### Revision 12.3 shared write service

All active source mutation paths now use `SourceWriteService`. The service owns complete-module validation, external signature conflict detection, recovery-journal preparation and finalization, atomic replacement, reparsing, and Workspace notification. Browser Member saves, File View saves, editable query saves, structural operations, and package file creation no longer call journal or atomic-write helpers directly. This boundary is the required insertion point for the future staged World overlay and selective commit modes.


##### Revision 12.4 Revision 12C completion

Removed the remaining parallel write APIs and converted recovery/I/O tests to `SourceWriteService`. The Recovery Journal now exposes `update_prepared()` for the file-existence metadata adjustment required by new-file transactions. There is one supported source mutation path, including application code and tests.
