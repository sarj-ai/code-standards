from pathlib import Path

from sarj_python_lint.__main__ import (
    _apply_baseline,  # pyright: ignore[reportPrivateUsage] — baseline severity is CLI behavior
    _baseline_counts,  # pyright: ignore[reportPrivateUsage] — baseline severity is CLI behavior
    main,
)
from sarj_python_lint.rule_base import Diagnostic, Severity


def test_two_sentence_error_fails(tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("# First fact. Second fact.\nvalue = 1\n")

    assert main(["check", "--rule", "prefer-single-sentence-comment", str(target)]) == 1


def test_three_sentence_error_fails(tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("# First fact. Second fact. Third fact.\nvalue = 1\n")

    assert main(["check", "--rule", "no-long-comment", str(target)]) == 1


def test_warnings_are_visible_even_when_errors_are_baselined() -> None:
    path = Path("example.py")
    warning = Diagnostic(path, 1, 1, "SARJ999", "shorten", Severity.WARNING)
    error = Diagnostic(path, 2, 1, "SARJ091", "too long")

    assert _baseline_counts([warning, error]) == {"example.py": {"SARJ091": 1}}
    assert _apply_baseline([warning, error], {"example.py": {"SARJ091": 1}}) == [warning]
