# PyBrowser Revision 7

Revision 7 adds fast navigation and world-wide search.

## Commands

- `Ctrl+P`: quick-open a module by dotted name or path
- `Ctrl+T`: quick-open an indexed class, method, function, or entity
- `Ctrl+Shift+F`: search text across every Python module in the world
- `Alt+Left` / `Alt+Right`: structural navigation history
- `Ctrl+Alt+G`: go to a source line
- Existing `Ctrl+F`, `Ctrl+G` Find Next, and `Ctrl+L` Abandon Changes remain unchanged

Quick dialogs filter incrementally using space-separated terms. Search results include dotted module, line, column, and source preview. Selecting a result resolves the containing browser entity and highlights the occurrence. Navigation continues to honor the unsaved-edit lock.

## Run

```powershell
py -3.14 -m pip install -e .[dev]
py -3.14 -m pybrowser
py -3.14 -m pytest
```


### Revision 7.1
- Function and method labels use `name  (arg1, arg2)` formatting, including empty `()`.
- Parameter blocks are painted cream in the Members pane.
- Editor and Members context menus provide **Implementers of...**.
- Members context menu provides **Senders of...**.
- Multi-result query windows provide a result list and syntax-highlighted source preview; double-click navigates the main browser.


#### Revision 7.2
- Centralizes the source-code font in `pybrowser.appearance`.
- Every shared `Editor` automatically uses 0xProto Nerd Font at 11 points.
- Implementers and Senders previews now match the main editor, and future shared-editor dialogs inherit the same font.
