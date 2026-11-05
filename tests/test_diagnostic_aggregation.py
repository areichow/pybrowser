from pathlib import Path
from pybrowser.diagnostic_aggregation import DiagnosticAggregation, decorate, summarize
from pybrowser.parser import build_index
from pybrowser.semantic import NativeDiagnostic, SemanticModule


def diagnostic(path, severity, line, rule, message="concern"):
    return NativeDiagnostic(path, severity, message, line, 1, line, 2, rule)


def test_summary_precedence_glyph_counts_and_tooltips():
    path = Path("app.py")
    values = [diagnostic(path, "information", 2, "hint"), diagnostic(path, "warning", 3, "warn")]
    summary = summarize(values)
    assert summary.highest == "warning"
    assert summary.glyph == "▲2"
    assert summary.color == "#dca8ac"
    assert decorate("app.py", summary) == "▲2 app.py"
    assert "warn" in summary.tooltip("app.py")


def test_aggregation_by_module_scope_category_and_member():
    path = Path("app.py").resolve()
    text = "class App:\n    # category: lifecycle\n    def start(self):\n        missing()\n"
    scopes = build_index(path, text)
    member = next(m for scope in scopes if scope.name == "App" for m in scope.members if not m.synthetic)
    values = (
        diagnostic(path, "warning", 3, "duplicate-definition"),
        diagnostic(path, "information", 4, "possibly-undefined-local"),
    )
    module = SemanticModule(path, (), (), values)
    aggregation = DiagnosticAggregation({path: module})
    assert aggregation.module(path).count == 2
    assert aggregation.scope(path, "App", scopes).count == 2
    scope = next(scope for scope in scopes if scope.name == "App")
    assert aggregation.category(path, scope, "lifecycle").count == 2
    assert aggregation.member(path, member).count == 2


def test_category_metadata_warning_aggregates_by_name():
    path = Path("app.py").resolve()
    text = "# category: abandoned\nprint('x')\n"
    scopes = build_index(path, text)
    item = diagnostic(path, "warning", 1, "unused-category-metadata", "Category 'abandoned' is not associated with a following Member")
    module = SemanticModule(path, (), (), (item,))
    aggregation = DiagnosticAggregation({path: module})
    assert aggregation.category(path, scopes[0], "abandoned").count == 1
