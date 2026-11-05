# PyBrowser Revision 2

Stage 2 modularizes the Rev 1 prototype and hardens source editing. It includes lossless member replacement, full-module validation, atomic writes, SHA-256 conflict detection, unsaved-edit protection, selection restoration, syntax-error positioning, a default dark theme, and pytest coverage for categories, decorators, async methods, multiline signatures, CRLF, encoding cookies, and external changes.

## Run

```powershell
py -3.14 -m pip install -e .[dev]
py -3.14 -m pybrowser
pytest
```

Open a file directly with `py -3.14 -m pybrowser path\to\app.py`.
