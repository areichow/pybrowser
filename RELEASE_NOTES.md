# PyBrowser 0.12.24.6 Release Notes

Release date: 2026-11-10

PyBrowser 0.12.24.6 is the first release checkpoint after completing the recovery journal, structural undo and redo, shared write service, Manual Commit overlay, staged-change review and recovery, and large-World responsiveness work.

## Highlights

- **Structural Python browsing:** Navigate ordinary Python source as Modules, Scopes, Categories, and Members.
- **Safe Member editing:** Reversible class indentation projection, complete-module LibCST and AST validation, exact encoding and newline preservation, stable SHA-256 conflict checks, and atomic replacement.
- **Recovery and history:** Durable SQLite-indexed before/after snapshots, Structural History, hash-guarded undo and redo, startup recovery, pinning, and retention controls.
- **Auto-Commit and Manual Commit:** Write through immediately or durably stage source in the World overlay, review diffs, commit selected files, commit all files, or abandon staged work.
- **Crash-safe staged commits:** Per-file durable progress and explicit recovery for interrupted multi-file commits.
- **Shared Workspace:** Browser, File View, queries, indexing, references, and staged source operate on one effective World.
- **Large-World performance:** Content-only refresh, asynchronous filesystem discovery, incremental indexing, known-write watcher suppression, and a callable-suite fast save path.
- **Visible version:** Browser title bars now display `PyBrowser 0.12.24.6` so the running build is immediately identifiable.

## Measured performance

Measurements used a Django World containing 2,942 Python modules on Windows with Python 3.14.2.

- Auto-Commit callable-suite saves: **324 to 342 ms** total.
- Auto-Commit signature-changing save with complete structural reparse: **531 ms** total.
- Warm Manual Commit callable-suite saves: **98 to 100 ms** total.
- Manual Commit signature-changing save: **174 ms** total.
- Single-module indexing benchmark median: approximately **4.9 ms**.
- Redundant directory scans after known PyBrowser writes are suppressed.

These measurements are workload and storage dependent. Auto-Commit intentionally retains durable SQLite and snapshot flushing.

## Validation

The release candidate passed on Windows:

```text
226 passed
Ruff F821: all checks passed
Focused structural GUI suite: 3 passed
```

The focused GUI suite covers duplicate-and-rename behavior and repeated Member saves in Auto-Commit and Manual Commit modes.

## Important behavior

- Auto-Commit is enabled by default.
- In Manual Commit mode, Ctrl+S stages a complete validated source image without changing the physical file.
- Type checking remains unavailable while staged overlays exist until overlay mirror materialization is implemented.
- Git operations remain explicit. PyBrowser does not automatically commit, reset, checkout, stash, or amend.
- Python 3.14 and PySide6 6.8 or newer are required.

## Known limitations

- Sender analysis is lexical and does not perform complete runtime type inference.
- Method-kind conversion supports only single-line signatures.
- Staged deletion and rename/move are not yet implemented.
- BasedPyright and Pyright cannot yet consume Manual Commit overlays.
- Shared PyBrowser locks cannot prevent a non-PyBrowser process from modifying a file at the exact instant of replacement; final stable-signature checks narrow that window.

## Upgrade notes

No project-source migration is required. Recovery journal schema migrations are automatic through schema version 7. Existing active Manual Commit overlays are restored from verified snapshots when the World is reopened.
