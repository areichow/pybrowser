# PyBrowser Revision 3

Revision 3 completes the single-file browser model. Every direct module or class-body statement is represented, while nested classes receive their own qualified scopes.

## Highlights

- Nested class scopes such as `Outer.Inner`
- Module and class docstrings
- Class variables, constants, ordinary variables, `__all__`, and type aliases
- Decorator labels for properties, setters, static methods, class methods, and overloads
- Descriptive labels for `if`, `for`, `while`, `with`, `try`, and `match` blocks
- Synthetic categories: Documentation, Imports, Types, Constants, Variables, Class Variables, Module Metadata, Functions, Runnable, Executable Code, and Uncategorized
- Explicit `# category:` comments override inferred categories
- `<entire category>` editing for contiguous categories containing multiple members
- Tooltips retain longer source descriptions when a browser label is shortened
- All Revision 2 safety behavior and dark-theme styling

## Run

```powershell
py -3.14 -m pip install -e .[dev]
py -3.14 -m pybrowser
py -3.14 -m pytest
```
