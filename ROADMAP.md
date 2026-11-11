# PyBrowser Roadmap

## Current release

Version 0.12.24.6 establishes the stable source-safety, recovery, Manual Commit, and large-World performance foundation.

## Next milestone: 0.13 Git context

Git remains explicit. This milestone adds read-only repository awareness and suggested commands without executing destructive Git operations.

1. Detect repository root, branch or detached HEAD, and current HEAD commit.
2. Record repository context in new recovery transactions.
3. Show tracked, modified, staged, and untracked state for changed files.
4. Add Git context to Structural History and Staged Changes.
5. Provide copyable `git add` and `git commit` suggestions.
6. Add repository fixtures covering linked worktrees, detached HEAD, untracked files, and repositories with spaces in paths.

## Following milestone: complete overlay consumers

1. Materialize a temporary overlay mirror for BasedPyright and Pyright.
2. Run type checking against staged source without changing the working tree.
3. Clean mirrors after successful runs and recover stale mirrors safely after crashes.
4. Make the mirror implementation reusable by future run/test commands.

## Staged structural operations

1. Durable staged deletion.
2. Staged rename and move with old/new path conflict checks.
3. Multi-path overlay identity and effective-World updates.
4. Commit and recovery UI for create, modify, delete, and rename operations in one batch.

## Release engineering

1. Add GitHub Actions for Windows and Linux tests, Ruff F821, and package build checks.
2. Add an explicit project license before publishing a public repository.
3. Add source distributions and wheels using `python -m build`.
4. Decide whether the first GitHub release ships source only or includes a frozen Windows executable.
5. Add signed tags or documented checksum publication for release artifacts.

## Later product work

- Improve semantic senders and references beyond lexical matching.
- Support multiline signatures in method-kind conversion.
- Add optional exact transient cursor-selection restoration across general reloads.
- Evaluate background Auto-Commit durability only if the current 300 to 350 ms measured save latency becomes a practical problem.
