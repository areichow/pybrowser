import json
from pathlib import Path
from pybrowser.typecheck import parse_json_output


def test_parse_pyright_json_uses_one_based_locations():
    payload = json.dumps({
        "version": "1.2.3",
        "generalDiagnostics": [{
            "file": "C:/work/app.py", "severity": "error",
            "message": "Argument is incompatible", "rule": "reportArgumentType",
            "range": {"start": {"line": 4, "character": 8}, "end": {"line": 4, "character": 12}},
        }],
        "summary": {"filesAnalyzed": 3, "errorCount": 1, "warningCount": 0, "informationCount": 0, "timeInSec": 0.25},
    })
    result = parse_json_output(payload, "basedpyright", 1)
    assert result.version == "1.2.3"
    assert result.files_analyzed == 3
    diagnostic = result.diagnostics[0]
    assert diagnostic.line == 5
    assert diagnostic.column == 9
    assert diagnostic.rule == "reportArgumentType"


def test_parse_empty_diagnostics():
    payload = json.dumps({"version": "1", "generalDiagnostics": [], "summary": {"filesAnalyzed": 1, "errorCount": 0, "warningCount": 0, "informationCount": 0, "timeInSec": 0.1}})
    result = parse_json_output(payload, "pyright")
    assert result.diagnostics == ()
    assert result.error_count == 0
