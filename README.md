# PyBrowser Revision 8

Revision 8 matures the shared source editor and persists editor preferences.

## Editing

- Line-number gutter with active-line emphasis
- Smart indentation after `:` and dedent after `return`, `raise`, `break`, `continue`, and `pass`
- Tab and Shift+Tab indentation for selections
- `Ctrl+/` comment toggling
- Automatic `()`, `[]`, and `{}` pairs
- Matching-bracket highlighting
- `Ctrl+H` Replace and Replace All within the current entity
- Existing `Ctrl+F`, `Ctrl+G`, `Ctrl+S`, and `Ctrl+L` behavior retained

## Preferences

**Edit > Preferences** controls:

- Code font family
- Code font size from 7 to 32 points
- Tab width from 1 to 12 spaces
- Visible whitespace
- Dark or light application theme

Preferences and main-window geometry are stored through `QSettings`. Because Implementers, Senders, and future source previews use the shared `Editor`, they inherit the code font, tab width, whitespace display, line numbers, bracket matching, and syntax highlighting.

## Run

```powershell
py -3.14 -m pip install -e .[dev]
py -3.14 -m pybrowser
py -3.14 -m pytest
```
