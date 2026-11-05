from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from .model import Document, Member

IDENTIFIER_RE = re.compile(r"^[A-Za-z_]\w*$")
CATEGORY_RE = re.compile(r"^(?P<indent>[ \t]*)#[ \t]*category[ \t]*:[ \t]*(?P<name>[^\r\n#]+?)\s*$", re.I | re.M)


class StructuralEditError(ValueError):
    pass


def _line_start(text: str, offset: int) -> int:
    return text.rfind("\n", 0, offset) + 1

def _category_directive_span(document: Document, member: Member):
    """Return the category directive immediately associated with a member."""
    start = _line_start(document.text, member.span.start)
    cursor = start
    while cursor > 0:
        previous_end = cursor - 1
        previous_start = document.text.rfind("\n", 0, previous_end) + 1
        line = document.text[previous_start:previous_end].rstrip("\r")
        stripped = line.strip()
        match = CATEGORY_RE.fullmatch(line)
        if match:
            return previous_start, cursor, match
        if stripped and not stripped.startswith("@") and not stripped.startswith("#"):
            break
        cursor = previous_start
    return None


@dataclass(frozen=True, slots=True)
class StructuralEdit:
    text: str
    scope: str
    category: str
    preferred_name: str


def validate_identifier(name: str) -> str:
    name = name.strip()
    if not IDENTIFIER_RE.fullmatch(name):
        raise StructuralEditError(f"{name!r} is not a valid Python identifier")
    return name


def _newline(document: Document) -> str:
    return document.newline


def _append_block(text: str, block: str, newline: str) -> str:
    text = text.rstrip("\r\n")
    return text + newline * 2 + block.rstrip("\r\n") + newline


def _class_node(text: str, qualified_scope: str) -> ast.ClassDef:
    tree = ast.parse(text)
    names = qualified_scope.split(".")
    body = tree.body
    found = None
    for name in names:
        found = next((node for node in body if isinstance(node, ast.ClassDef) and node.name == name), None)
        if found is None:
            raise StructuralEditError(f"Class {qualified_scope!r} was not found")
        body = found.body
    return found


def _line_offset(text: str, line: int) -> int:
    starts = [0]
    for match in re.finditer("\n", text):
        starts.append(match.end())
    return starts[min(max(0, line - 1), len(starts) - 1)]


def add_function(document: Document, name: str, category: str = "Functions") -> StructuralEdit:
    name = validate_identifier(name)
    nl = _newline(document)
    block = f"# category: {category}{nl}def {name}():{nl}    pass"
    return StructuralEdit(_append_block(document.text, block, nl), "<module>", category, name)


def add_class(document: Document, name: str, category: str = "Classes") -> StructuralEdit:
    name = validate_identifier(name)
    nl = _newline(document)
    block = f"# category: {category}{nl}class {name}:{nl}    pass"
    return StructuralEdit(_append_block(document.text, block, nl), name, "Executable Code", name)


def add_method(document: Document, scope: str, name: str, category: str, method_kind: str = "instance") -> StructuralEdit:
    if scope == "<module>":
        return add_function(document, name, category)
    name = validate_identifier(name)
    node = _class_node(document.text, scope)
    nl = _newline(document)
    indent = " " * (node.col_offset + 4)
    decorator = {"static": "@staticmethod", "class": "@classmethod", "property": "@property"}.get(method_kind)
    parameters = {"static": "", "class": "cls", "property": "self"}.get(method_kind, "self")
    lines = [f"{indent}# category: {category}"]
    if decorator:
        lines.append(f"{indent}{decorator}")
    lines.extend([f"{indent}def {name}({parameters}):", f"{indent}    pass"])
    insert = _line_offset(document.text, node.end_lineno + 1) if node.end_lineno else len(document.text)
    prefix = document.text[:insert].rstrip("\r\n")
    suffix = document.text[insert:]
    text = prefix + nl * 2 + nl.join(lines) + nl + suffix.lstrip("\r\n")
    return StructuralEdit(text, scope, category, name)


def delete_member(document: Document, member: Member) -> StructuralEdit:
    if member.synthetic:
        raise StructuralEditError("Select an individual entity before deleting")
    directive = _category_directive_span(document, member)
    start = directive[0] if directive else member.span.start
    text = document.text[:start] + document.text[member.span.end:]
    text = re.sub(r"(?:\r?\n){3,}", document.newline * 2, text)
    return StructuralEdit(text, member.scope, member.category, "")


def duplicate_member(document: Document, member: Member) -> StructuralEdit:
    if member.synthetic:
        raise StructuralEditError("Select an individual entity before duplicating")
    source = document.source(member)
    text = document.text[:member.span.end] + document.newline + source + document.text[member.span.end:]
    return StructuralEdit(text, member.scope, member.category, member.label)


def move_member(document: Document, member: Member, category: str) -> StructuralEdit:
    if member.synthetic:
        raise StructuralEditError("Select an individual entity before moving it")
    category = category.strip()
    if not category:
        raise StructuralEditError("Category cannot be empty")
    directive = _category_directive_span(document, member)
    text = document.text
    if directive:
        start, end, match = directive
        replacement = f"{match.group('indent')}# category: {category}{document.newline}"
        text = text[:start] + replacement + text[end:]
    else:
        source_line_start = _line_start(text, member.span.start)
        source_line_end = text.find("\n", source_line_start)
        if source_line_end < 0:
            source_line_end = len(text)
        line = text[source_line_start:source_line_end]
        indent = line[: len(line) - len(line.lstrip())]
        metadata = f"{indent}# category: {category}{document.newline}"
        text = text[:source_line_start] + metadata + text[source_line_start:]
    return StructuralEdit(text, member.scope, category, member.label)


def rename_category(document: Document, old: str, new: str, scope: str | None = None) -> StructuralEdit:
    new = new.strip()
    if not new:
        raise StructuralEditError("Category cannot be empty")
    directives = {}
    for parsed_scope in document.scopes:
        if scope and parsed_scope.name != scope:
            continue
        for member in parsed_scope.members:
            if member.synthetic or member.category != old:
                continue
            directive = _category_directive_span(document, member)
            if directive:
                start, end, match = directive
                directives[(start, end)] = match
    text = document.text
    for (start, end), match in sorted(directives.items(), reverse=True):
        replacement = f"{match.group('indent')}# category: {new}{document.newline}"
        text = text[:start] + replacement + text[end:]
    if text == document.text:
        raise StructuralEditError("No explicit category directives were available to rename")
    return StructuralEdit(text, scope or "<module>", new, "")


def convert_method_kind(document: Document, member: Member, method_kind: str) -> StructuralEdit:
    if member.scope == "<module>" or member.synthetic:
        raise StructuralEditError("Select an individual class method")
    source = document.source(member)
    nl = document.newline
    lines = source.splitlines()
    def_index = next((i for i, line in enumerate(lines) if re.match(r"\s*(?:async\s+)?def\s+", line)), None)
    if def_index is None:
        raise StructuralEditError("Selected entity is not a method")
    indent = lines[def_index][: len(lines[def_index]) - len(lines[def_index].lstrip())]
    lines = [line for line in lines if line.strip() not in {"@staticmethod", "@classmethod", "@property"}]
    def_index = next(i for i, line in enumerate(lines) if re.match(r"\s*(?:async\s+)?def\s+", line))
    if method_kind in {"static", "class", "property"}:
        decorator = {"static": "@staticmethod", "class": "@classmethod", "property": "@property"}[method_kind]
        lines.insert(def_index, indent + decorator)
        def_index += 1
    line = lines[def_index]
    match = re.match(r"(?P<head>\s*(?:async\s+)?def\s+\w+\s*\()(?P<params>[^)]*)(?P<tail>\).*)", line)
    if not match:
        raise StructuralEditError("Only single-line method signatures can be converted in Revision 6")
    params = [value.strip() for value in match.group("params").split(",") if value.strip()]
    params = [value for value in params if value.split(":", 1)[0].split("=", 1)[0].strip() not in {"self", "cls"}]
    if method_kind in {"instance", "property"}:
        params.insert(0, "self")
    elif method_kind == "class":
        params.insert(0, "cls")
    lines[def_index] = match.group("head") + ", ".join(params) + match.group("tail")
    replacement = nl.join(lines) + (nl if source.endswith(("\n", "\r")) else "")
    text = document.text[:member.span.start] + replacement + document.text[member.span.end:]
    return StructuralEdit(text, member.scope, member.category, member.label.split("(", 1)[0].strip())


def create_package_init(directory: Path) -> Path:
    path = directory / "__init__.py"
    if path.exists():
        raise StructuralEditError(f"{path} already exists")
    path.write_text('"""Package initialization."""\n', encoding="utf-8", newline="")
    return path
