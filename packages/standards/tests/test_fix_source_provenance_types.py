from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import requires, version
import json
from pathlib import Path
import subprocess
import sys

from packaging.requirements import Requirement
from pydantic import BaseModel, Field

import sarj_standards


_CONFIG = Path(sarj_standards.__file__).parent / "configs" / "basedpyright.strict.json"
_ACCEPTED = """
from pathlib import Path
from typing import assert_type

from sarj_standards.libs.diagnostics import (
    AnalysisReport, Completion, Conclusion, Diagnostic, Fix, FixSafety,
    Location, Position, Region, Severity, TextEdit, ToolReport, to_json,
)

location = Location("case.py", region=Region(Position(0, 0, 0), Position(0, 0, 0)))
legacy = TextEdit(location, "prefix", "a" * 64)
enriched = TextEdit(location, "prefix", "a" * 64, expected_source_hash="b" * 64)
absent = TextEdit(location, "prefix", expected_source_hash=None)
assert_type(enriched.expected_source_hash, str | None)
fix = Fix("Insert prefix", FixSafety.SAFE, (enriched,))
diagnostic = Diagnostic("fixture", "Finding", Severity.WARNING, "fixture", location, fixes=(fix,))
report = AnalysisReport(Path("."), Completion.COMPLETE, Conclusion.FINDINGS, (ToolReport("fixture", Completion.COMPLETE, (diagnostic,)),))
legacy.as_dict()
enriched.as_dict(include_fix_source_hashes=True)
fix.as_dict(include_fix_source_hashes=True)
diagnostic.as_dict(include_fix_source_hashes=True)
report.as_dict(include_fix_source_hashes=True)
to_json(report, indent=None)
to_json(report, indent=2, include_fix_source_hashes=True)
"""


class _Point(BaseModel):
    line: int


class _Range(BaseModel):
    start: _Point


class _TypeDiagnostic(BaseModel):
    file: Path
    severity: str
    rule: str | None = None
    span: _Range = Field(validation_alias="range")


class _TypeReport(BaseModel):
    diagnostics: list[_TypeDiagnostic] = Field(validation_alias="generalDiagnostics")


@dataclass(frozen=True, slots=True)
class _TypecheckResult:
    exit_code: int
    report: _TypeReport


def test_installed_public_edit_and_serialization_types_preserve_old_calls_and_accept_opt_in(tmp_path: Path) -> None:
    result = _typecheck(tmp_path, _ACCEPTED)

    assert result.exit_code == 0
    assert result.report.diagnostics == []


def test_installed_public_edit_and_serialization_types_reject_invalid_hashes_and_flags(tmp_path: Path) -> None:
    statements = [
        f'TextEdit(location, "prefix", expected_source_hash={invalid})  # rejected-reportArgumentType\n'
        for invalid in ("1", "True", "b'bytes'")
    ]
    statements.append('TextEdit(location, "prefix", None, "b" * 64)  # rejected-reportCallIssue\n')
    statements.extend(
        f'{owner}.as_dict(include_fix_source_hashes="true")  # rejected-reportArgumentType\n'
        for owner in ("enriched", "fix", "diagnostic", "report")
    )
    statements.extend(
        (
            "enriched.as_dict(True)  # rejected-reportCallIssue\n",
            'to_json(report, include_fix_source_hashes="true")  # rejected-reportArgumentType\n',
        )
    )
    source = _ACCEPTED + "".join(statements)
    expected = {
        line: text.split("# rejected-", 1)[1] for line, text in enumerate(source.splitlines()) if "# rejected-" in text
    }

    result = _typecheck(tmp_path, source)

    assert result.exit_code == 1
    assert {item.file for item in result.report.diagnostics} == {tmp_path / "fix_source_contract.py"}
    assert {item.severity for item in result.report.diagnostics} == {"error"}
    assert len(result.report.diagnostics) == len(expected)
    assert {item.span.start.line: item.rule for item in result.report.diagnostics} == expected


def _typecheck(root: Path, source: str) -> _TypecheckResult:
    installed_requirements = requires("code-standards")
    assert installed_requirements is not None
    [pin] = [
        requirement for text in installed_requirements if (requirement := Requirement(text)).name == "basedpyright"
    ]
    assert str(pin.specifier) == f"=={version('basedpyright')}"
    config = root / "pyrightconfig.json"
    config.write_text(json.dumps({"extends": str(_CONFIG)}), encoding="utf-8")
    fixture = root / "fix_source_contract.py"
    fixture.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "basedpyright",
            "--pythonpath",
            sys.executable,
            "--outputjson",
            "--project",
            str(config),
            str(fixture),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert not result.stderr, result.stderr
    return _TypecheckResult(exit_code=result.returncode, report=_TypeReport.model_validate_json(result.stdout))
