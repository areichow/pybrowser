from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TypeDiagnostic:
    file: Path
    severity: str
    message: str
    line: int
    column: int
    end_line: int
    end_column: int
    rule: str = ""

    @property
    def display(self) -> str:
        rule = f" [{self.rule}]" if self.rule else ""
        return f"{self.file.name}:{self.line}:{self.column}  {self.severity.upper()}{rule}  {self.message}"


@dataclass(frozen=True, slots=True)
class TypeCheckResult:
    checker: str
    version: str
    diagnostics: tuple[TypeDiagnostic, ...]
    files_analyzed: int
    error_count: int
    warning_count: int
    information_count: int
    elapsed_seconds: float
    return_code: int
    fatal_error: str = ""


def discover_checker(preferred="auto", configured_path="") -> tuple[str, str] | None:
    candidates = []
    if configured_path:
        candidates.append((preferred if preferred != "auto" else Path(configured_path).stem, configured_path))
    names = [preferred] if preferred in {"basedpyright", "pyright"} else ["basedpyright", "pyright"]
    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append((name, found))
        # PyPI basedpyright is frequently installed into this interpreter's Scripts/bin.
        sibling = Path(sys.executable).parent / (name + (".exe" if os.name == "nt" else ""))
        if sibling.exists():
            candidates.append((name, str(sibling)))
    return candidates[0] if candidates else None


def parse_json_output(payload: str, checker: str, return_code=0) -> TypeCheckResult:
    data = json.loads(payload)
    diagnostics = []
    for item in data.get("generalDiagnostics", []):
        start = item.get("range", {}).get("start", {})
        end = item.get("range", {}).get("end", {})
        diagnostics.append(TypeDiagnostic(
            Path(item.get("file", "")), item.get("severity", "information"),
            item.get("message", ""), int(start.get("line", 0)) + 1,
            int(start.get("character", 0)) + 1, int(end.get("line", 0)) + 1,
            int(end.get("character", 0)) + 1, item.get("rule", ""),
        ))
    summary = data.get("summary", {})
    return TypeCheckResult(
        checker, str(data.get("version", "")), tuple(diagnostics),
        int(summary.get("filesAnalyzed", 0)), int(summary.get("errorCount", 0)),
        int(summary.get("warningCount", 0)), int(summary.get("informationCount", 0)),
        float(summary.get("timeInSec", 0.0)), return_code,
    )


def run_type_check(target: Path, preferred="auto", configured_path="", python_path="", timeout=180) -> TypeCheckResult:
    discovered = discover_checker(preferred, configured_path)
    if not discovered:
        return TypeCheckResult(preferred, "", (), 0, 0, 0, 0, 0.0, 127, "No basedpyright or pyright executable was found")
    checker, executable = discovered
    command = [executable, "--outputjson"]
    if python_path:
        command.extend(["--pythonpath", python_path])
    command.append(str(target))
    try:
        completed = subprocess.run(command, cwd=str(target if target.is_dir() else target.parent), capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return TypeCheckResult(checker, "", (), 0, 0, 0, 0, 0.0, 2, str(exc))
    try:
        result = parse_json_output(completed.stdout, checker, completed.returncode)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        detail = completed.stderr.strip() or completed.stdout.strip() or str(exc)
        return TypeCheckResult(checker, "", (), 0, 0, 0, 0, 0.0, completed.returncode, detail)
    return result
