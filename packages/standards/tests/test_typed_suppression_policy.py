from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from pydantic import BaseModel, Field
import pytest


CONFIG_DIRECTORY = Path(__file__).parents[1] / "src/sarj_standards/configs"


class BasedPyrightDiagnostic(BaseModel):
    rule: str


class BasedPyrightReport(BaseModel):
    general_diagnostics: list[BasedPyrightDiagnostic] = Field(validation_alias="generalDiagnostics")


@pytest.mark.parametrize("profile", ["pyright.strict.json", "basedpyright.strict.json"])
@pytest.mark.parametrize(
    ("source", "expected_rules"),
    [
        (
            (
                "def value() -> str:\n"
                "    return 1  # type: ignore[reportAttributeAccessIssue] -- external stubs omit the field\n"
            ),
            ["reportReturnType"],
        ),
        (
            (
                "def value() -> str:\n"
                "    return 1  # pyright: ignore[reportAttributeAccessIssue] -- external stubs omit the field\n"
            ),
            ["reportReturnType", "reportUnnecessaryTypeIgnoreComment"],
        ),
        (
            (
                "def value() -> str:\n"
                "    return 1  # pyright: ignore[reportReturnType] -- deliberately exercise the adapter boundary\n"
            ),
            [],
        ),
        (
            (
                "def value() -> str:\n"
                '    return "ok"  # pyright: ignore[reportReturnType] -- deliberately exercise the adapter boundary\n'
            ),
            ["reportUnnecessaryTypeIgnoreComment"],
        ),
        (
            (
                "def value() -> str:\n"
                '    return int("x", wrong=True)  # pyright: ignore[reportReturnType] -- isolate the return error from the call error\n'
            ),
            ["reportCallIssue"],
        ),
    ],
)
def test_pyright_suppressions_respect_diagnostic_codes(
    tmp_path: Path, profile: str, source: str, expected_rules: list[str]
) -> None:
    config = tmp_path / "pyrightconfig.json"
    config.write_text(json.dumps({"extends": str(CONFIG_DIRECTORY / profile)}), encoding="utf-8")
    example = tmp_path / "example.py"
    example.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "basedpyright", "--outputjson", "--project", str(config), str(example)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert not result.stderr
    report = BasedPyrightReport.model_validate_json(result.stdout)
    assert sorted(item.rule for item in report.general_diagnostics) == sorted(expected_rules)
    assert result.returncode == bool(expected_rules)
