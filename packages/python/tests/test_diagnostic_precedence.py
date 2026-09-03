from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sarj_python_lint.__main__ import analyze, deduplicate_diagnostics, main
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


def test_typed_section_precedence_uses_the_owning_docstring_across_lines(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "def decode(value: str) -> str:\n"
        '    """Decode a value.\n\n'
        "    Args:\n"
        "        value (str): Value to decode.\n"
        '    """\n'
        "    return value\n",
        encoding="utf-8",
    )

    diagnostics = analyze(["docstring-args-restate-signature", "no-typed-doc-sections"], [source])

    assert [finding.code for finding in diagnostics] == ["SARJ092"]
    assert diagnostics[0].line == 5


def test_typed_return_precedence_uses_the_owning_docstring_across_lines(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "def decode(value: str) -> str:\n"
        '    """Produce the wire representation.\n\n'
        "    Returns:\n"
        "        str\n"
        '    """\n'
        "    return value\n",
        encoding="utf-8",
    )

    diagnostics = analyze(["docstring-returns-restate-signature", "no-typed-doc-sections"], [source])

    assert [finding.code for finding in diagnostics] == ["SARJ092"]
    assert diagnostics[0].line == 5


def test_owner_precedence_never_crosses_docstrings(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "def decode(value: str) -> str:\n"
        '    """Decode a value.\n\n'
        "    Args:\n"
        "        value (str): Value to decode.\n"
        '    """\n'
        "    return value\n\n"
        "def encode(value: str) -> str:\n"
        '    """Encode a value.\n\n'
        "    Args:\n"
        "        value: Value to encode.\n"
        '    """\n'
        "    return value\n",
        encoding="utf-8",
    )

    diagnostics = analyze(["docstring-args-restate-signature", "no-typed-doc-sections"], [source])

    assert [finding.code for finding in diagnostics] == ["SARJ086", "SARJ092"]


def test_nominal_id_boundary_suppresses_generic_swap_prone_signature(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "def transfer(\n    source_account_id: str,\n    destination_account_id: str,\n) -> None: ...\n",
        encoding="utf-8",
    )

    diagnostics = analyze(["require-keyword-only-swap-prone-params", "prefer-nominal-id-types"], [source])

    assert [finding.code for finding in diagnostics] == ["SARJ093"]


def test_precedence_never_crosses_source_locations() -> None:
    diagnostics = [_diagnostic("SARJ050", line=2), _diagnostic("SARJ088", line=3)]

    assert deduplicate_diagnostics(diagnostics) == diagnostics


def test_specific_warning_never_hides_a_generic_error() -> None:
    generic = Diagnostic(Path("service.py"), 3, 5, "SARJ050", "generic", Severity.ERROR)
    specific = Diagnostic(Path("service.py"), 3, 5, "SARJ084", "specific", Severity.WARNING)

    assert deduplicate_diagnostics([generic, specific]) == [generic, specific]


def test_suppressing_specific_finding_preserves_unsuppressed_generic_twin(
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

    assert status == 1
    output = capsys.readouterr().out
    assert "SARJ050" in output
    assert "SARJ088" not in output
