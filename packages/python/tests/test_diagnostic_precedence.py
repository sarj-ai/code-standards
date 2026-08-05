from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sarj_python_lint.__main__ import deduplicate_diagnostics, main
from sarj_python_lint.rule_base import Diagnostic, Severity


if TYPE_CHECKING:
    import pytest


def _diagnostic(code: str, *, line: int = 3) -> Diagnostic:
    return Diagnostic(Path("service.py"), line, 5, code, code)


def test_specific_test_docstring_finding_suppresses_generic_restatements() -> None:
    diagnostics = [_diagnostic("SARJ050"), _diagnostic("SARJ085"), _diagnostic("SARJ088")]

    assert [finding.code for finding in deduplicate_diagnostics(diagnostics)] == ["SARJ088"]


def test_typed_section_finding_suppresses_per_section_twins() -> None:
    diagnostics = [_diagnostic("SARJ086"), _diagnostic("SARJ087"), _diagnostic("SARJ092")]

    assert [finding.code for finding in deduplicate_diagnostics(diagnostics)] == ["SARJ092"]


def test_precedence_never_crosses_source_locations() -> None:
    diagnostics = [_diagnostic("SARJ050", line=2), _diagnostic("SARJ088", line=3)]

    assert deduplicate_diagnostics(diagnostics) == diagnostics


def test_specific_warning_never_hides_a_generic_error() -> None:
    generic = Diagnostic(Path("service.py"), 3, 5, "SARJ050", "generic", Severity.ERROR)
    specific = Diagnostic(Path("service.py"), 3, 5, "SARJ084", "specific", Severity.WARNING)

    assert deduplicate_diagnostics([generic, specific]) == [generic, specific]


def test_suppressing_specific_finding_does_not_reveal_generic_twin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "test_service.py"
    source.write_text(
        "def test_returns_none_when_missing():\n"
        '    """Test that it returns None when missing."""  # sarj-noqa: SARJ088\n'
        "    assert lookup() is None\n",
        encoding="utf-8",
    )

    status = main(
        [
            "check",
            "--rule",
            "redundant-docstring",
            "--rule",
            "restated-test-docstring",
            str(source),
        ]
    )

    assert status == 0
    assert not capsys.readouterr().out
