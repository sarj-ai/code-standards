from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.__main__ import main
from sarj_sql_lint.rules import REGISTRY


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("rule_id", ["mixed-migration-phases", "no-application-schema-check"])
def test_advisory_findings_preserve_success(tmp_path: Path, capsys: pytest.CaptureFixture[str], rule_id: str) -> None:
    rule = REGISTRY[rule_id]
    example = next(case for case in rule.public_examples() if case.expected_count)
    for file in example.files:
        path = tmp_path / file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file.source, encoding="utf-8")
    assert main(["check", "--rule", rule_id, str(tmp_path / example.focus_path)]) == 0
    captured = capsys.readouterr()
    assert f"{rule.code} warning:" in captured.out
    assert not captured.err


def test_explicit_missing_input_is_an_operator_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.sql"

    assert main(["check", "--rule", "prefer-jsonb", str(missing)]) == 2
    assert f"input does not exist: {missing}" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [[], ["check"], ["check", "missing.sql"], ["unknown"]],
    ids=("missing-command", "missing-files-and-rule", "missing-rule", "unknown-command"),
)
def test_cli_usage_errors_exit_two(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as failure:
        main(argv)
    assert failure.value.code == 2


@pytest.mark.parametrize(
    "argv",
    [["--help"], ["-h"], ["--version"], ["check", "--help"]],
    ids=("help", "short-help", "version", "check-help"),
)
def test_cli_help_and_version_exit_zero(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 0
    assert "sarj-sql-lint" in capsys.readouterr().out


def test_cli_repeated_rules_and_option_like_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "--source.sql").write_text("", encoding="utf-8")
    assert main(["check", "--rule", "prefer-jsonb", "--rule", "prefer-jsonb", "--", "--source.sql"]) == 0
