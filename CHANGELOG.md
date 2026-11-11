# Changelog

All notable user-facing changes are documented here.

## [0.12.24.6] - 2026-11-10

### Added
- Version number in the main Browser title bar and Qt application metadata.
- Durable Auto-Commit and Manual Commit workflows with staged-change review.
- Structural History, safe undo and redo, and startup recovery.
- Crash-recoverable staged commit batches.
- Background large-World discovery and incremental module indexing.
- Opt-in `PYBROWSER_PROFILE=1` performance records.

### Improved
- Callable-suite saves reuse safely rebased structural spans after complete candidate validation.
- Existing-module saves no longer rebuild the World or synchronously resolve all module paths.
- Known internal writes suppress duplicate filesystem-watcher reloads.
- Repeated Member saves preserve exact boundaries, indentation projection, selection, and following Members.

### Fixed
- Member projection loss after search-state reset.
- Incorrect fast-path Member boundaries when the editor omitted a final newline.
- Ambiguous Member occurrence matching during span rebasing.
- Commit Selected being reported as an external source change.
- Windows Qt top-level window deletion and menu-registry races.

See `RELEASE_NOTES.md` for the complete release checkpoint.
