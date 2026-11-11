# PyBrowser Source Safety and Recovery Architecture

This document records the maintained contracts for source mutation, recovery, and Manual Commit. Historical revision notes were retired at the 0.12.24.6 release checkpoint; release history now belongs in `CHANGELOG.md` and `RELEASE_NOTES.md`.

## Source-write boundary

`SourceWriteService` is the only supported application source-write boundary. Every mutation must construct and validate complete candidates, acquire shared path locks in canonical order, compare stable SHA-256 signatures, persist complete snapshots and authoritative SQLite metadata, atomically replace or exclusively create files, finalize recovery state, and publish one origin-aware Workspace notification.

## Recovery journal

- SQLite schema version 7 is authoritative; JSON manifests are repairable portable mirrors.
- Complete before and after snapshots are ordinary inspectable files.
- WAL mode, `synchronous=FULL`, foreign keys, and a 5000 ms busy timeout are required.
- Undo and redo require exact hashes.
- Incomplete save, undo, redo, prune, and staged-commit states require explicit recovery classification.
- Pinned, incomplete, active overlay, active undo/redo, and active staged-batch transactions are retention protected.

## Manual Commit overlay

`WorldSourceStore` is the shared read boundary for physical and staged source. Browser, File View, queries, indexing, search, and references consume the effective World. Manual Commit saves validated snapshots into the journal while leaving physical source unchanged.

Commit Selected and Commit All use durable staged-commit batches with per-file progress. Active overlays remain authoritative until every intended after image is present and SQLite finalization succeeds.

## Member projection

Only Member editors use reversible dedentation. The exact common tabs/spaces prefix is removed for display and restored to every non-empty edited line. File View stays literal. Search state must not mutate the active `MemberProjection`.

Callable-suite saves may reuse prepared scopes only when AST comparison proves the callable structure outside the suite is unchanged. Boundaries come from the completed candidate, and the edited occurrence is matched by scope plus exact literal span.

## Large-World behavior

Existing-module content changes do not imply a module-set change. Directory discovery runs in a coalescing background task, full indexing uses process workers and batched Qt delivery, changed modules receive incremental indexing, and known writes suppress duplicate watcher reloads. Physical cache identity uses mtime and size while integrity boundaries retain SHA-256.

## Git boundary

Git is complementary history, not the source-write mechanism. PyBrowser may inspect Git state and suggest commands, but it must not automatically commit, reset, checkout, stash, or amend.
