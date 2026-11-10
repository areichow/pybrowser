# Member Editor Indentation Plan

## Goal

Present an individual Member at editor column zero while preserving its exact structural indentation when it is written back to the module. File View remains a literal, byte-faithful whole-file view and must never dedent source.

## Core model

The Member editor should use a reversible projection rather than modifying the stored `Document.text`:

```text
file source -> dedented Member projection -> edited projection -> reindented candidate -> full-module validation -> atomic write
```

For a class method stored as:

```python
class Service:
    @classmethod
    def build(cls):
        if ready:
            return cls()
```

The Member editor displays:

```python
@classmethod
def build(cls):
    if ready:
        return cls()
```

The recorded base indentation is the exact prefix before the first syntactic line of the Member, four spaces in this example. A nested class method may record eight or more spaces.

## Safety rules

1. **Only Member editors use the projection.** File View always shows and edits literal module source.
2. **Derive indentation from the parsed Member span, not from user preferences.** Preserve tabs, spaces, and mixed prefixes exactly.
3. **Remove only the exact common structural prefix.** Do not use unrestricted `textwrap.dedent()`, which can normalize malformed or intentionally unusual indentation.
4. **Blank lines remain blank.** Do not add trailing spaces to empty lines during reindentation.
5. **Every non-empty edited line receives the recorded prefix when saving.** Relative indentation inside the Member remains unchanged.
6. **Reject escaped indentation.** If edited non-empty lines cannot form a valid standalone projection or the reconstructed module fails LibCST and AST validation, do not write.
7. **Validate the complete reconstructed module before atomic replacement.** Existing SHA-256 conflict checks remain mandatory.
8. **Preserve newline style, encoding, final newline, permissions, and unrelated source exactly.**
9. **Decorators are part of the Member projection.** The base prefix is calculated from the first decorator when present.
10. **Multiline strings are text, not indentation instructions.** Prefix removal and addition are line-prefix operations only; string contents beyond the structural prefix are untouched.

## Proposed API

Add a small immutable projection record:

```python
@dataclass(frozen=True, slots=True)
class MemberProjection:
    text: str
    prefix: str


def project_member(document: Document, member: Member) -> MemberProjection: ...
def restore_member(projection: MemberProjection, edited_text: str, newline: str) -> str: ...
```

`Document.source(member)` remains literal source for File View and structural operations. The Browser and query editors call `project_member()`. Save calls `restore_member()` before the existing `replacement()` operation.

## Prefix calculation

- Find the first non-empty line in the literal Member source.
- Capture its exact leading whitespace as `prefix`.
- Require every non-empty source line to begin with that prefix. If not, mark the Member as unsafe for projected editing and display literal indentation.
- Remove exactly that prefix from each non-empty line.

This handles decorators, nested classes, tabs, and mixed project styles without guessing an indentation width.

## Cursor and diagnostic mapping

Line numbers do not change, only columns. Store `len(prefix)` as the column offset:

```text
file_column = editor_column + len(prefix)
editor_column = max(1, file_column - len(prefix))
```

For tabs, visual columns and character offsets differ. Diagnostic navigation should map by character prefix length, while rendering remains controlled by the editor's configured tab width.

## Save sequence

1. Capture the edited projected text.
2. Normalize only newline separators to the document newline convention.
3. Reapply the exact recorded prefix to every non-empty line.
4. Replace only the original Member span in the unchanged document text.
5. Parse with LibCST.
6. Compile with `ast.PyCF_ONLY_AST`.
7. Confirm the file signature still matches.
8. Write atomically.
9. Reparse and reproject the saved Member.
10. Restore Browser selection and cursor position.

## Cases to test before enabling by default

- Module-level function, prefix `""`
- Class method with four spaces
- Nested-class method with eight spaces
- Tab-indented class
- Decorated method
- Async method
- Multiline signature
- Blank lines inside a method
- Triple-quoted strings containing indentation
- Continuation lines inside parentheses
- A method containing a nested function or class
- CRLF and non-UTF-8 source
- Rename while saving
- Syntax error in projected text
- External modification between load and save

## Implementation status

**Complete in Revision 12.19.** Browser Member editors and editable query windows use the reversible projection, **Dedent Member editor** defaults on, and File View remains literal. Unsafe mixed-prefix Members fall back to literal display and saving.

Completion verification includes:

- Parameterized round-trip invariants for module functions, class and nested-class methods, decorators, async methods, multiline signatures, blank lines, triple-quoted strings, continuation lines, nested functions and classes, and CRLF source.
- Exact tab-prefix and unsafe mixed-prefix behavior.
- Projected saves through `SourceWriteService` for UTF-8 CRLF and Latin-1 CRLF files.
- Projection-aware diagnostic navigation that converts literal file offsets after the target Member projection is loaded.
- Complete-module LibCST and AST validation, SHA-256 conflict checks, journaling, and atomic replacement.

## Consciously deferred UI enhancements

The indentation architecture is complete. These are optional UI refinements, not safety or correctness gaps:

- Preserve an exact transient cursor selection across every watcher-driven or general module reload. Structural Member identity is preserved, but ephemeral `QTextCursor` selections may reset.
- Display a specialized escaped-projection-indentation message when complete-module validation can only report the underlying Python syntax error.
- Add visual-column presentation for tabs in diagnostic labels. Navigation maps character offsets correctly while Qt renders using the configured tab width.

## Rollout result

The preference remains enabled by default because the round-trip invariant is exercised across the complete fixture matrix. File View remains the escape hatch and literal source-of-truth display for unusual files.
