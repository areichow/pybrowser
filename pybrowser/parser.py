from __future__ import annotations
import ast
import io
import re
import tokenize
from pathlib import Path
import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider
from .model import Document, Kind, Member, Scope, Span
from .saving import stable_read
from .conventions import canonical_category

CATEGORY_RE = re.compile(r"^[ \t]*#[ \t]*category[ \t]*:[ \t]*(?P<name>[^\r\n#]+?)[ \t]*$", re.I)

class ParseError(ValueError):
    def __init__(self, message: str, line: int | None = None, column: int | None = None):
        super().__init__(message)
        self.line = line
        self.column = column

def _line_starts(text: str) -> list[int]:
    values = [0]
    values.extend(match.end() for match in re.finditer("\n", text))
    return values

def _line_end(text: str, starts: list[int], line: int) -> int:
    return starts[line] if line < len(starts) else len(text)

def _node_start(node, position, positions) -> int:
    decorators = getattr(node, "decorators", ())
    return positions[decorators[0]].start.line if decorators else position.start.line

def _directive_before(text: str, start_line: int, lower_bound: int) -> tuple[str | None, int | None]:
    lines = text.splitlines()
    index = start_line - 1
    while index >= lower_bound:
        value = lines[index - 1]
        match = CATEGORY_RE.match(value)
        if match:
            return canonical_category(match.group("name")), index
        stripped = value.strip()
        if stripped and not stripped.startswith(("#", "@")):
            break
        index -= 1
    return None, None

def _span_start(text: str, node_start: int, lower_bound: int) -> int:
    # Category directives are browser metadata. Keep them outside the Member's
    # editable source span so the code editor starts at decorators/def/class.
    return node_start

def _code(node) -> str:
    return cst.Module([]).code_for_node(node).strip()

def _is_main_guard(node) -> bool:
    if not isinstance(node, cst.If):
        return False
    return _code(node.test).replace(" ", "") in {'__name__=="__main__"', "__name__=='__main__'"}

def _is_docstring(node) -> bool:
    if not isinstance(node, cst.SimpleStatementLine) or len(node.body) != 1:
        return False
    expression = node.body[0]
    return isinstance(expression, cst.Expr) and isinstance(expression.value, (cst.SimpleString, cst.ConcatenatedString))

def _assignment_target(node) -> str:
    target = node.targets[0].target if isinstance(node, cst.Assign) else node.target
    return _code(target)

def _inferred_category(node, in_class: bool) -> str:
    if _is_docstring(node):
        return "-- docs --"
    if isinstance(node, cst.SimpleStatementLine):
        if node.body and all(isinstance(item, (cst.Import, cst.ImportFrom)) for item in node.body):
            return "-- imports --"
        if len(node.body) == 1 and isinstance(node.body[0], (cst.Assign, cst.AnnAssign, cst.AugAssign)):
            name = _assignment_target(node.body[0])
            if name == "__all__":
                return "Module Metadata"
            if name.isupper():
                return "-- constants --"
            return "Class Variables" if in_class else "-- variables --"
    type_alias = getattr(cst, "TypeAlias", None)
    if type_alias and isinstance(node, type_alias):
        return "Types"
    if isinstance(node, cst.FunctionDef):
        return "as yet unclassified" if in_class else "-- functions --"
    if _is_main_guard(node):
        return "Runnable"
    return "Executable Code"

def _function_label(node: cst.FunctionDef) -> str:
    prefix = "async " if node.asynchronous else ""
    params = _code(node.params)
    if not params.startswith("("):
        params = f"({params})"
    # LibCST parameter rendering can be compact; normalize comma spacing for the browser.
    params = re.sub(r",\s*", ", ", " ".join(params.split()))
    label = f"{prefix}{node.name.value}  {params}"
    decorators = {_code(item.decorator) for item in node.decorators}
    if "property" in decorators:
        label += " [property]"
    elif any(item.endswith(".setter") for item in decorators):
        label += " [setter]"
    elif "classmethod" in decorators:
        label += " [classmethod]"
    elif "staticmethod" in decorators:
        label += " [staticmethod]"
    elif "overload" in decorators or "typing.overload" in decorators:
        label += " [overload]"
    return label

def _short(value: str, limit: int = 100) -> str:
    one_line = " ".join(value.split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1] + "…"

def _compound(node) -> tuple[Kind, str, str]:
    if isinstance(node, cst.If):
        condition = _code(node.test)
        return Kind.IF, f"if {_short(condition)}", f"if {condition}"
    if isinstance(node, cst.For):
        prefix = "async " if node.asynchronous is not None else ""
        full = f"{prefix}for {_code(node.target)} in {_code(node.iter)}"
        return Kind.FOR, _short(full), full
    if isinstance(node, cst.While):
        full = f"while {_code(node.test)}"
        return Kind.WHILE, _short(full), full
    if isinstance(node, cst.With):
        prefix = "async " if node.asynchronous is not None else ""
        full = prefix + "with " + ", ".join(_code(item.item) for item in node.items)
        return Kind.WITH, _short(full), full
    if isinstance(node, (cst.Try, getattr(cst, "TryStar", cst.Try))):
        names = []
        for handler in node.handlers:
            names.append(_code(handler.type) if handler.type else "bare")
        full = "try / except " + ", ".join(names) if names else "try / finally"
        return Kind.TRY, _short(full), full
    if isinstance(node, cst.Match):
        full = f"match {_code(node.subject)}"
        return Kind.MATCH, _short(full), full
    return Kind.STATEMENT, type(node).__name__, type(node).__name__

def _make_member(text, node, scope, category, positions, starts, in_class, lower_bound) -> Member:
    position = positions[node]
    first = _span_start(text, _node_start(node, position, positions), lower_bound)
    span = Span(starts[first - 1], _line_end(text, starts, position.end.line), first, position.end.line)
    tooltip = text[span.start:span.end].splitlines()[0].strip()
    if _is_docstring(node):
        return Member(scope, category, "module docstring" if scope == "<module>" else "class docstring", Kind.DOCUMENTATION, span, tooltip=tooltip)
    if isinstance(node, cst.SimpleStatementLine):
        if node.body and all(isinstance(item, (cst.Import, cst.ImportFrom)) for item in node.body):
            return Member(scope, category, _short(tooltip), Kind.IMPORTS, span, tooltip=tooltip)
        if len(node.body) == 1 and isinstance(node.body[0], (cst.Assign, cst.AnnAssign, cst.AugAssign)):
            target = _assignment_target(node.body[0])
            return Member(scope, category, target, Kind.ASSIGNMENT, span, tooltip=tooltip)
        return Member(scope, category, _short(tooltip) or f"statement at line {first}", Kind.STATEMENT, span, tooltip=tooltip)
    type_alias = getattr(cst, "TypeAlias", None)
    if type_alias and isinstance(node, type_alias):
        name = _code(node.name)
        return Member(scope, category, name, Kind.TYPE_ALIAS, span, tooltip=tooltip)
    if isinstance(node, cst.FunctionDef):
        return Member(scope, category, _function_label(node), Kind.METHOD if in_class else Kind.FUNCTION, span, tooltip=tooltip)
    if _is_main_guard(node):
        return Member(scope, category, 'if __name__ == "__main__"', Kind.MAIN, span, tooltip=tooltip)
    kind, label, full = _compound(node)
    return Member(scope, category, label, kind, span, tooltip=full)

def _group_imports(items: list[Member], text: str) -> list[Member]:
    grouped: list[Member] = []
    for item in items:
        if (grouped and item.kind == grouped[-1].kind == Kind.IMPORTS
                and item.category == grouped[-1].category
                and not text[grouped[-1].span.end:item.span.start].strip()):
            previous = grouped.pop()
            span = Span(previous.span.start, item.span.end, previous.span.first, item.span.last)
            grouped.append(Member(item.scope, item.category, f"imports: lines {span.first}-{span.last}", Kind.IMPORTS, span, tooltip="contiguous import block"))
        else:
            grouped.append(item)
    return grouped

def _add_category_members(items: list[Member]) -> tuple[Member, ...]:
    """Return real Members only; whole-category editing belongs in File View."""
    return tuple(items)


def _walk_class(text, node, qualified_name, positions, starts, scopes, parent=None):
    items: list[Member] = []
    position = positions[node]
    if isinstance(node.body, cst.IndentedBlock):
        for child in node.body.body:
            if isinstance(child, cst.ClassDef):
                nested = f"{qualified_name}.{child.name.value}"
                _walk_class(text, child, nested, positions, starts, scopes, qualified_name)
                continue
            start = _node_start(child, positions[child], positions)
            explicit, _ = _directive_before(text, start, position.start.line + 1)
            category = explicit or _inferred_category(child, True)
            items.append(_make_member(text, child, qualified_name, category, positions, starts, True, position.start.line + 1))
    scopes.append(Scope(qualified_name, _add_category_members(_group_imports(items, text)), parent))

def build_index(path: Path, text: str) -> tuple[Scope, ...]:
    try:
        module = cst.parse_module(text)
    except cst.ParserSyntaxError as exc:
        raise ParseError(str(exc), getattr(exc, "raw_line", None), getattr(exc, "raw_column", None)) from exc
    wrapper = MetadataWrapper(module, unsafe_skip_copy=True)
    positions = wrapper.resolve(PositionProvider)
    starts = _line_starts(text)
    module_items: list[Member] = []
    class_scopes: list[Scope] = []
    for node in module.body:
        if isinstance(node, cst.ClassDef):
            _walk_class(text, node, node.name.value, positions, starts, class_scopes)
            continue
        node_start = _node_start(node, positions[node], positions)
        explicit, _ = _directive_before(text, node_start, 1)
        category = explicit or _inferred_category(node, False)
        module_items.append(_make_member(text, node, "<module>", category, positions, starts, False, 1))
    module_scope = Scope("<module>", _add_category_members(_group_imports(module_items, text)))
    return (module_scope, *class_scopes)

def document_from_stable(path: Path, stable) -> Document:
    path = Path(path).resolve()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(stable.data).readline)
    text = stable.data.decode(encoding)
    return Document(path, text, encoding, "\r\n" if "\r\n" in text else "\n", text.endswith(("\n", "\r")), stable.signature, build_index(path, text))

def read_document(path: Path) -> Document:
    path = Path(path).resolve()
    return document_from_stable(path, stable_read(path))

def replacement(document: Document, member: Member, new: str) -> str:
    old = document.source(member)
    new = new.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    if document.newline != "\n":
        new = new.replace("\n", document.newline)
    if old.endswith(("\n", "\r")):
        new += document.newline
    return document.text[:member.span.start] + new + document.text[member.span.end:]

def validate(text: str, filename: str) -> None:
    try:
        cst.parse_module(text)
        compile(text, filename, "exec", ast.PyCF_ONLY_AST)
    except cst.ParserSyntaxError as exc:
        raise ParseError(str(exc), getattr(exc, "raw_line", None), getattr(exc, "raw_column", None)) from exc
    except SyntaxError as exc:
        raise ParseError(exc.msg, exc.lineno, exc.offset) from exc
