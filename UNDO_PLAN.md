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

### 12A Recovery Journal
- Durable JSON manifests, SQLite index, and complete before/after snapshots
- Retention, startup recovery detection, Structural History, and Restore As

### 12B Structural Undo and Redo
- Hash-guarded workspace undo/redo
- Cross-window unsaved-edit protection and refresh
- Browser location restoration

### 12C Shared Write Service
- One validation, conflict-check, journal, atomic-write, reparse, and notification boundary

### 12D Git Context and Multi-file Transactions
- Git metadata, explicit multi-file writes, partial-commit recovery, and diff context

### 12E Journal-only Staging Overlay
- Virtual World reads, selective commit, retained staged changes, and safe discard

### Deferred write / image-style commit mode

A future phase will add a preference choosing between **Write through immediately** and **Stage in journal until commit**. Staged mode requires a World overlay filesystem so every Browser, File View, semantic index, type check, query, and runtime launch reads the staged after-snapshot rather than stale disk content. Planned File commands are **Commit All Changes** and **Commit Changes...**, with the latter presenting a transaction/file summary and allowing selective commits. Quit and World switching must prompt to commit, retain staged changes, or discard them. This is intentionally deferred until the shared `SourceWriteService` and virtual World overlay are implemented; merely skipping `os.replace()` in the current architecture would cause indexers and other windows to read inconsistent source.


### Revision 12.1 SQLite journal index

`journal.sqlite3` is now the authoritative metadata index while complete source snapshots and portable per-transaction `manifest.json` files remain on the filesystem. The database uses foreign keys, WAL mode, `synchronous=FULL`, and a 5000 ms busy timeout. On World open, PyBrowser imports Revision 12.0 JSON-only transactions, reconciles rows with transaction directories, and marks transactions damaged when required snapshot files are missing. This schema includes `committed_to_disk` so the future staged overlay can query pending changes without another metadata migration.


#### Revision 12.3 shared write service

All active source mutation paths now use `SourceWriteService`. The service owns complete-module validation, external signature conflict detection, recovery-journal preparation and finalization, atomic replacement, reparsing, and Workspace notification. Browser Member saves, File View saves, editable query saves, structural operations, and package file creation no longer call journal or atomic-write helpers directly. This boundary is the required insertion point for the future staged World overlay and selective commit modes.


##### Revision 12.4 Revision 12C completion

Removed the remaining parallel write APIs and converted recovery/I/O tests to `SourceWriteService`. The Recovery Journal now exposes `update_prepared()` for the file-existence metadata adjustment required by new-file transactions. There is one supported source mutation path, including application code and tests.


#### Revision 12.5 hardening

12A to 12C are hardened with durable snapshot flushing, formal SQLite schema version 3, typed transaction statuses and operations, redo stack ordering by `undone_at`, redo-branch supersession, post-commit warning metadata, explicit incomplete-transaction disposition, broader terminal-state retention, and failure-injection/branching-history coverage. The delivery labels are now: 12A Recovery Journal, 12B Structural Undo/Redo, 12C Shared Write Service, 12D Git Context and Multi-file Transactions, and 12E Journal-only Staging Overlay.


##### Revision 12.6 final hardening

Completed legacy SQLite migrations, restart-aware snapshot requirements, missing-after reconstruction, Structural History recovery disposition controls, commit-before-supersede ordering, conditional state transitions, active-chain retention protection, and post-commit warning results. Revision 12A through 12C can now serve as the stable foundation for 12D.


### Revision 12.7 final authority and maintenance hardening

SQLite is authoritative during reconciliation, stale JSON mirrors are repaired, core commit completion is isolated from fallible housekeeping, reparse failures preserve committed editor state, and retention enforces configured limits without deleting active undo/redo candidates.


### Revision 12.8 structural and concurrency completion

Completed structural command regression repair, duplicate-selection safety, schema 4 recovery timestamps, portable manifest reconstruction, SQLite-first metadata transitions, claimed undo/redo transitions, and crash-aware pruning. Development validation now includes Ruff F821 undefined-name checking.


#### Revision 12.9 final transient-state and conflict hardening

Interrupted undoing and redoing claims now have restart dispositions based on before/after hashes. Pruning uses durable pending-deletion records and startup completion. Existing-file saves use stable read-and-verify snapshots, new-file writes use exclusive no-replace creation, metadata transitions merge from authoritative SQLite state, and multiple post-commit warnings are preserved.


#### Revision 12.10 final 12A-12C freeze

Document loads and saves now use stable byte images, cooperative path locks, and a final pre-replacement signature check. Established transaction transitions are SQLite-first, portable mirrors are rebuilt from authoritative rows, transient history damage requires complete snapshots, and recovery controls identify interrupted save, undo, and redo actions explicitly.

#### Revision 12.14 deterministic GUI testing and duplicate restoration

The focused Duplicate Member GUI regression disables unrelated process-pool indexing and filesystem watchers, converts unexpected modal dialogs into immediate test failures, and tears down Qt windows explicitly. Duplicate-label restoration initializes the complete matching-row set before selecting a valid source-order fallback. Indexing workers no longer catch BaseException.


#### Revision 12.15 literal Document offset correction

The focused Duplicate Member regression now compares the selected Member span with literal `Document.text`, not `Path.read_text()`. On Windows, universal-newline translation removes CR characters and makes later offsets appear smaller than the parser's correct CRLF-preserving offsets. A CRLF parser regression fixes this contract.


#### Revision 12.16 duplicate rename-selection lifecycle

The GUI regression now distinguishes durable structural selection from ephemeral editor selection. Duplicate Member must select the inserted occurrence and its identifier immediately. A subsequent general module reload must preserve the inserted occurrence, but the rename selection is explicitly reapplied before simulating typing.


##### Revision 12.17 shared path-lock service

Path locking is extracted into `PathLockService`. Source saves, exclusive file creation, undo, and redo now use the same journal-owned lock namespace. Multi-path acquisition deduplicates resolved paths and locks them in canonical case-folded order, which establishes the deadlock-avoidance rule required by Stage 12D. History restoration acquires every affected lock before claiming `undoing` or `redoing`, so lock contention leaves transaction state unchanged.


##### Revision 12.18 platform-neutral recovery tests

Recovery hash and interrupted-history tests now construct and verify exact bytes rather than text translated by the Windows newline layer. Source-inspection tests explicitly decode UTF-8, and the Workspace test uses a real `World` contract. An LF/CRLF regression verifies that manifest hashes equal the actual before and after snapshot bytes.


##### Revision 12.20 overlay-capable source and multi-file commit foundation

Added `WorldSourceStore` as the Workspace-owned source read boundary. Browser and File View document loads, editable queries, Implementers, Senders, World search, references, and process-based indexing can consume overlay bytes while Auto-Commit behavior remains unchanged. `SourceWriteService.save_documents()` now validates every candidate, acquires all path locks in canonical order, records one multi-file recovery transaction, replaces each source, and rolls back earlier replacements in reverse order if a later replacement fails. Manual staging, commit UI, quit disposition, and durable overlay restoration remain subsequent revisions.


###### Revision 12.20.1 overlay identity and effective-World hardening

Separated visible overlay signatures from retained physical disk signatures so repeated staged edits can detect stale editors without losing the original disk conflict baseline. Overlay replacement is guarded under the shared path lock. Virtual staged Python files are merged into the Workspace effective World for module discovery, indexing, queries, search, and quick-open. ModuleIndexCache now keys entries by the visible source signature, including virtual SHA-256 signatures. Multi-file fallback reparsing uses the corresponding file manifest hash rather than file zero. Durable journal transactions and Manual Commit UI remain Revision 12.21 and later.


#### Revision 12.21 durable single-file staging and Manual Commit

Schema 6 adds authoritative `active_overlays` rows that point to complete staged transactions and retain each physical disk baseline. `SourceWriteService` routes the existing save API through Auto-Commit or Manual Commit mode. Manual saves validate source, lock the path, durably write complete before and after snapshots, update SQLite, then publish the overlay. Repeated saves supersede the prior staged transaction while preserving the original disk baseline. Workspace startup restores active overlays from verified snapshots. Virtual new Python files remain absent from disk until exclusive creation at commit. Commit Changes to Disk validates every staged baseline under canonical multi-path locks and writes all active overlays as one runtime-atomic operation with rollback. Quit and World switching offer Commit, Abandon, View, and Cancel. Type checking is disabled while overlays are active until a mirror-tree implementation is added. Deferred work includes selective commit, staged deletion/rename, type-check mirrors, and per-file crash progress for multi-file replacement.


###### Revision 12.21.1 Manual Commit notification and GUI-test hardening

Overlay publication no longer emits an origin-less synchronous reload while `SourceWriteService` is still completing a save. The service publishes or removes the overlay silently, then sends one origin-aware Workspace notification. Workspace source notifications also publish the current effective World so virtual modules appear and disappear in Browser trees without a physical directory event. Physical directory refresh updates the Workspace disk baseline before merging overlays. GUI tests now isolate the global `source/writeMode` setting, fail immediately on instance `QMessageBox.exec()`, and clean up without invoking staged-change lifecycle prompts.


##### Revision 12.22 dedicated Staged Changes review

`File > View Staged Changes` now opens a modeless Staged Changes window instead of the general Structural History window. It lists one active overlay per path, distinguishes existing files from virtual new files, rechecks physical baselines on refresh, highlights external conflicts, and shows a unified disk-to-staged snapshot diff with transaction metadata. Actions include Commit Selected, Abandon Selected, Open Staged Source, Commit All, Abandon All, and Refresh. Commit Selected is disabled when the selected physical baseline conflicts, while abandon and inspection remain available. Quit and World-switch `View Changes` now open this dedicated window and cancel the pending lifecycle action.


###### Revision 12.22.1 staged finalization authority and lifecycle hardening

Staged commit finalization now commits authoritative SQLite state before best-effort JSON mirror reconstruction and history notification. Mirror or notification failures return post-commit warnings and never trigger physical rollback after SQLite has committed. Commit Selected, Commit All, Abandon Selected, and Abandon All route through Workspace unsaved-window protection. Staged Changes uses a bound Qt slot, `WA_DeleteOnClose`, and deleted-child pruning; its summary explains that only active overlays are listed and its diff labels the left side `baseline/` rather than current disk.
