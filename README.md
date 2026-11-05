# PyBrowser Revision 6

Revision 6 introduces structural source editing from the Smalltalk-style browser.

## Structure menu

- New Function
- New Class
- New Method, including instance, static, class, and property forms
- New Category guidance
- Rename Category
- Move Entity to Category
- Duplicate Entity
- Delete Entity
- Convert Method Kind
- Create Package `__init__.py`

Every structural change is assembled in memory, validated as a complete Python module, checked for external disk changes, written atomically, reparsed, and reselected in the browser. Structural commands reject synthetic `<entire category>` members where an individual entity is required. Method-kind conversion intentionally supports single-line signatures in Revision 6 and reports a clear error for multiline signatures.

## Run

```powershell
py -3.14 -m pip install -e .[dev]
py -3.14 -m pybrowser
py -3.14 -m pytest
```

## Revision 6.1 navigation lock

When an entity has unsaved edits, answering **No** to the abandon prompt now atomically restores the module, scope, category, and member selections under Qt signal blockers. The editor text is never reloaded, the unsaved indicator remains active, focus returns to the editor, and navigation is cancelled.
