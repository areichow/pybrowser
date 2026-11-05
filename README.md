# PyBrowser Revision 5

Revision 5 adds responsive background world indexing and hardens project refresh behavior.

## Stage 5 features

- Parse project modules through `QThreadPool` and `QRunnable`, never from the UI thread.
- Tag every indexing run with a generation number so stale results cannot overwrite a newer world.
- Cancel obsolete indexing runs when another world opens or the project tree changes.
- Cache valid module indexes using modification time and file size signatures.
- Mark modules with syntax errors directly in the module tree without preventing the world from opening.
- Show live indexing progress in the status bar.
- Show indexed scope and browser-item counts in module tooltips.
- Debounce filesystem events by 250 ms to avoid repeated project rescans during editor or Git operations.
- Retain cached entries for unchanged modules while removing entries for deleted modules.
- Continue watching project directories and the active module.
- Preserve recent worlds, directory browsing, Find, structural browsing, and atomic editing.

## Run

```powershell
py -3.14 -m pip install -e .[dev]
py -3.14 -m pybrowser
py -3.14 -m pytest
```
