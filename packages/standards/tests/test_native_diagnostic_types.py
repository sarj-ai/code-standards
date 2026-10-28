from __future__ import annotations

from importlib.metadata import requires, version
import json
from pathlib import Path
import subprocess
import sys

from packaging.requirements import Requirement
from pydantic import BaseModel, Field

import sarj_standards


_CONFIG = Path(sarj_standards.__file__).parent / "configs" / "basedpyright.strict.json"
_CONSTRUCTORS = ("PythonDiagnostic", "SqlDiagnostic", "IacDiagnostic")
_ACCEPTED = """
from pathlib import Path
from typing import assert_type

from sarj_iac_lint.rule_base import Diagnostic as IacDiagnostic
from sarj_python_lint.rule_base import Diagnostic as PythonDiagnostic
from sarj_rule_contracts import DefaultLevel, DiagnosticSeverity, Severity, diagnostic_severity
from sarj_sql_lint.rule_base import Diagnostic as SqlDiagnostic

path = Path("source.txt")

def emitted(level: DiagnosticSeverity) -> tuple[PythonDiagnostic, SqlDiagnostic, IacDiagnostic]:
    return (
        PythonDiagnostic(path, 1, 1, "fixture", "finding", severity=level),
        SqlDiagnostic(path, 1, 1, "fixture", "finding", severity=level),
        IacDiagnostic(path, 1, 1, "fixture", "finding", severity=level),
    )

def validated(level: DefaultLevel) -> tuple[PythonDiagnostic, SqlDiagnostic, IacDiagnostic]:
    return emitted(diagnostic_severity(level))

errors = emitted(Severity.ERROR)
warnings = emitted(DefaultLevel.WARNING)
python_default = PythonDiagnostic(path, 1, 1, "fixture", "finding")
sql_default = SqlDiagnostic(path, 1, 1, "fixture", "finding")
iac_default = IacDiagnostic(path, 1, 1, "fixture", "finding")
assert_type(python_default.severity, DiagnosticSeverity)
assert_type(sql_default.severity, DiagnosticSeverity)
assert_type(iac_default.severity, DiagnosticSeverity)
"""


class _Point(BaseModel):
    line: int


class _Range(BaseModel):
    start: _Point


class _TypeDiagnostic(BaseModel):
    file: Path
    severity: str
    rule: str | None = None
    message: str
    span: _Range = Field(validation_alias="range")


class _TypeReport(BaseModel):
    diagnostics: list[_TypeDiagnostic] = Field(validation_alias="generalDiagnostics")


class _TypecheckResult(BaseModel):
    exit_code: int
    report: _TypeReport


def _typecheck(root: Path, source: str) -> _TypecheckResult:
    installed_requirements = requires("code-standards")
    assert installed_requirements is not None
    [pin] = [
        requirement for text in installed_requirements if (requirement := Requirement(text)).name == "basedpyright"
    ]
    assert str(pin.specifier) == f"=={version('basedpyright')}"
    config = root / "pyrightconfig.json"
    config.write_text(json.dumps({"extends": str(_CONFIG)}), encoding="utf-8")
    fixture = root / "severity_contract.py"
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


def test_installed_native_constructors_accept_emitted_and_validated_severity_types(tmp_path: Path) -> None:
    result = _typecheck(tmp_path, _ACCEPTED)

    assert result.report.diagnostics == []
    assert result.exit_code == 0


def test_installed_native_constructors_reject_configuration_and_untyped_severity_values(tmp_path: Path) -> None:
    statements = [
        f'{constructor}(path, 1, 1, "fixture", "finding", severity={invalid})  # rejected-{constructor}-{index}\n'
        for constructor in _CONSTRUCTORS
        for index, invalid in enumerate(("DefaultLevel.OFF", '"error"', '"warning"', "None", "True"))
    ]
    policy_statements = (
        f'    {constructor}(path, 1, 1, "fixture", "finding", severity=level)  # rejected-{constructor}-policy\n'
        for constructor in _CONSTRUCTORS
    )
    source = _ACCEPTED + "".join(statements)
    source += "\ndef from_policy(level: DefaultLevel) -> None:\n" + "".join(policy_statements)
    expected_lines = {line for line, text in enumerate(source.splitlines()) if "# rejected-" in text}

    result = _typecheck(tmp_path, source)
    report = result.report

    assert result.exit_code == 1
    assert {diagnostic.file for diagnostic in report.diagnostics} == {tmp_path / "severity_contract.py"}
    assert {diagnostic.severity for diagnostic in report.diagnostics} == {"error"}
    assert {diagnostic.rule for diagnostic in report.diagnostics} == {"reportArgumentType"}
    assert len(report.diagnostics) == len(expected_lines)
    assert {diagnostic.span.start.line for diagnostic in report.diagnostics} == expected_lines
