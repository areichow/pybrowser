from __future__ import annotations

import ast
import builtins
import io
import re
import symtable
import tokenize
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

CATEGORY_LINE = re.compile(r"^(?P<indent>[ \t]*)#[ \t]*category[ \t]*:[ \t]*(?P<name>[^#\r\n]+?)\s*$", re.I)


@dataclass(frozen=True, slots=True)
class SemanticSymbol:
    name: str
    kind: str
    path: Path
    scope: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class SemanticReference:
    name: str
    kind: str  # read, write, call, import, base, decorator, annotation
    path: Path
    scope: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class NativeDiagnostic:
    file: Path
    severity: str
    message: str
    line: int
    column: int
    end_line: int
    end_column: int
    rule: str
    source: str = "PYBROWSER"

    @property
    def display(self):
        return f"{self.file.name}:{self.line}:{self.column} {self.source} {self.rule} {self.message}"


@dataclass(frozen=True, slots=True)
class SemanticModule:
    path: Path
    symbols: tuple[SemanticSymbol, ...]
    references: tuple[SemanticReference, ...]
    diagnostics: tuple[NativeDiagnostic, ...]


def read_source(path: Path) -> str:
    raw = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    return raw.decode(encoding)


class SemanticVisitor(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.scope = ["<module>"]
        self.symbols = []
        self.references = []
        self.diagnostics = []
        self.definitions = [defaultdict(list)]
        self.local_defs = [set()]
        self.local_loads = [[]]

    @property
    def scope_name(self):
        return ".".join(self.scope[1:]) if len(self.scope) > 1 else "<module>"

    def symbol(self, name, kind, node):
        self.symbols.append(SemanticSymbol(name, kind, self.path, self.scope_name, node.lineno, node.col_offset + 1))
        if kind in {"class", "function", "method"}:
            self.definitions[-1][name].append((kind, node.lineno, node.col_offset + 1))
        self.local_defs[-1].add(name)

    def reference(self, name, kind, node):
        self.references.append(SemanticReference(name, kind, self.path, self.scope_name, node.lineno, node.col_offset + 1))

    def enter_scope(self, name, node, body):
        self.scope.append(name)
        self.definitions.append(defaultdict(list)); self.local_defs.append(set()); self.local_loads.append([])
        for statement in body: self.visit(statement)
        self._finish_scope(node)
        self.definitions.pop(); self.local_defs.pop(); self.local_loads.pop(); self.scope.pop()

    def _finish_scope(self, node):
        for name, definitions in self.definitions[-1].items():
            if len(definitions) > 1:
                kinds = ", ".join(kind for kind, _line, _col in definitions)
                _kind, line, column = definitions[-1]
                self.diagnostics.append(NativeDiagnostic(self.path, "warning", f"{name!r} is defined more than once in scope {self.scope_name} ({kinds})", line, column, line, column + len(name), "duplicate-definition"))
        if self.scope_name != "<module>":
            known = set().union(*self.local_defs)
            known.update(dir(builtins))
            known.update({"self", "cls", "__class__"})
            for name, item in self.local_loads[-1]:
                if name not in known:
                    self.diagnostics.append(NativeDiagnostic(self.path, "information", f"Name {name!r} may be undefined in local scope {self.scope_name}", item.lineno, item.col_offset + 1, item.lineno, item.col_offset + 1 + len(name), "possibly-undefined-local"))

    def visit_Import(self, node):
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            self.symbol(name, "import", node); self.reference(alias.name, "import", node)

    def visit_ImportFrom(self, node):
        for alias in node.names:
            name = alias.asname or alias.name
            self.symbol(name, "import", node); self.reference(name, "import", node)

    def visit_ClassDef(self, node):
        self.symbol(node.name, "class", node)
        for base in node.bases:
            for child in ast.walk(base):
                if isinstance(child, ast.Name): self.reference(child.id, "base", child)
        for decorator in node.decorator_list:
            self._reference_expression(decorator, "decorator")
        self.enter_scope(node.name, node, node.body)

    def _visit_function(self, node, kind):
        self.symbol(node.name, kind, node)
        for decorator in node.decorator_list: self._reference_expression(decorator, "decorator")
        self.scope.append(node.name); self.definitions.append(defaultdict(list)); self.local_defs.append(set()); self.local_loads.append([])
        args = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
        if node.args.vararg: args.append(node.args.vararg)
        if node.args.kwarg: args.append(node.args.kwarg)
        for arg in args:
            self.symbol(arg.arg, "parameter", arg)
            if arg.annotation: self._reference_expression(arg.annotation, "annotation")
        if node.returns: self._reference_expression(node.returns, "annotation")
        for statement in node.body: self.visit(statement)
        self._finish_scope(node)
        self.definitions.pop(); self.local_defs.pop(); self.local_loads.pop(); self.scope.pop()

    def visit_FunctionDef(self, node): self._visit_function(node, "method" if self.scope_name != "<module>" else "function")
    def visit_AsyncFunctionDef(self, node): self._visit_function(node, "method" if self.scope_name != "<module>" else "function")

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self.symbol(node.id, "assignment", node); self.reference(node.id, "write", node)
        elif isinstance(node.ctx, ast.Del): self.reference(node.id, "delete", node)
        else:
            self.reference(node.id, "read", node); self.local_loads[-1].append((node.id, node))

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name): self.reference(node.func.id, "call", node.func)
        elif isinstance(node.func, ast.Attribute): self.reference(node.func.attr, "call", node.func)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if not isinstance(getattr(node, "ctx", None), ast.Store): self.reference(node.attr, "read", node)
        self.generic_visit(node)

    def _reference_expression(self, node, kind):
        for child in ast.walk(node):
            if isinstance(child, ast.Name): self.reference(child.id, kind, child)
            elif isinstance(child, ast.Attribute): self.reference(child.attr, kind, child)


def _category_diagnostics(path: Path, text: str):
    lines = text.splitlines()
    values = []
    for index, line in enumerate(lines, 1):
        match = CATEGORY_LINE.match(line)
        if match: values.append((index, len(match.group("indent")) + 1, match.group("name").strip(), len(match.group("indent"))))
    diagnostics = []
    for line, column, name, indent in values:
        cursor = line
        associated = False
        duplicate = False
        while cursor < len(lines):
            cursor += 1
            candidate = lines[cursor - 1]
            stripped = candidate.strip()
            if not stripped or stripped.startswith("@") or (stripped.startswith("#") and not CATEGORY_LINE.match(candidate)): continue
            next_category = CATEGORY_LINE.match(candidate)
            if next_category:
                duplicate = True
                break
            candidate_indent = len(candidate) - len(candidate.lstrip())
            associated = candidate_indent == indent and bool(re.match(r"(?:async\s+def|def|class|import|from|[A-Za-z_]\w*\s*(?::[^=]+)?=)", stripped))
            break
        if duplicate:
            diagnostics.append(NativeDiagnostic(path, "warning", f"Category {name!r} is followed by another category directive before any Member", line, column, line, column + len(name), "duplicate-category-directive"))
        elif not associated:
            diagnostics.append(NativeDiagnostic(path, "warning", f"Category {name!r} is not associated with a following Member", line, column, line, column + len(name), "unused-category-metadata"))
    return diagnostics


def analyze_source(path: Path, text: str) -> SemanticModule:
    tree = ast.parse(text, filename=str(path), type_comments=True)
    # Constructing a stdlib symbol table validates Python's own lexical-scope model.
    symtable.symtable(text, str(path), "exec")
    visitor = SemanticVisitor(path)
    visitor.visit(tree)
    visitor._finish_scope(tree)
    diagnostics = list(visitor.diagnostics) + _category_diagnostics(path, text)
    return SemanticModule(path, tuple(visitor.symbols), tuple(visitor.references), tuple(diagnostics))


def analyze_path(path: Path) -> SemanticModule:
    return analyze_source(path.resolve(), read_source(path.resolve()))
