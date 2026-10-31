from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sarj_python_lint.rules.prefer_pytest_fixture_contract import PreferPytestFixtureContract

from sarj_standards import api
from sarj_standards.cli.main import main as cli_main
from sarj_standards.libs.diagnostics import Severity


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("example_id", "expected_severity", "expected_exit"),
    [
        ("concrete-injected-collaborator", Severity.ERROR, 1),
        ("concrete-store-fixture", Severity.WARNING, 0),
    ],
    ids=("proven-injection-error", "unobserved-export-warning"),
)
def test_fixture_contract_severity_survives_normal_policy_and_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    example_id: str,
    expected_severity: Severity,
    expected_exit: int,
) -> None:
    documentation = PreferPytestFixtureContract.documentation
    assert documentation is not None
    example = next(case for case in documentation.examples if case.example_id == example_id)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'fixture-contract-policy-example'\nversion = '1.0'\nrequires-python = '>=3.14'\n"
    )
    for file in example.files:
        path = tmp_path / file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file.source)
    target = tmp_path / example.focus_path
    selector = "python:prefer-pytest-fixture-contract"

    report = api.Standards(tmp_path).analyze([str(target)], rules=[selector])

    assert report.issues == ()
    assert [finding.severity for finding in report.diagnostics] == [expected_severity]
    assert report.exit_code == expected_exit
    assert cli_main(["--root", str(tmp_path), "check", "--rule", selector, str(target)]) == expected_exit
    assert "SARJ550" in capsys.readouterr().out
