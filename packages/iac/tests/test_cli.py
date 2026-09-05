from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_iac_lint.__main__ import main, read_baseline


if TYPE_CHECKING:
    from pathlib import Path


_RULE = "no-environment-conditional"

_TWO_BRANCHES = """
module "iam" {
  source                             = "./iam"
  team_platform_owner_privilege      = var.environment == "dev"
  developer_secret_access_v2_enabled = var.environment == "dev"
}
"""

_THREE_BRANCHES = (
    _TWO_BRANCHES
    + """
resource "google_storage_bucket" "b" {
  count = var.environment == "sandbox" ? 1 : 0
}
"""
)


def test_explicit_missing_input_is_an_operator_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.tf"

    assert main(["check", "--rule", "require-deletion-protection", str(missing)]) == 2
    assert f"input does not exist: {missing}" in capsys.readouterr().err


def test_update_baseline_records_the_counts_and_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "main.tf"
    src.write_text(_TWO_BRANCHES, encoding="utf-8")
    out = tmp_path / "baseline.json"

    assert main(["check", "--rule", _RULE, "--update-baseline", str(out), str(src)]) == 0
    assert "baseline written" in capsys.readouterr().out
    recorded = read_baseline(out)
    assert list(recorded.values()) == [{"SARJ204": 2}]


def test_a_baselined_file_stops_failing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "main.tf"
    src.write_text(_TWO_BRANCHES, encoding="utf-8")
    out = tmp_path / "baseline.json"
    assert main(["check", "--rule", _RULE, "--update-baseline", str(out), str(src)]) == 0
    capsys.readouterr()

    assert main(["check", "--rule", _RULE, "--baseline", str(out), str(src)]) == 0
    assert not capsys.readouterr().out


def test_a_new_finding_beyond_the_baseline_still_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "main.tf"
    src.write_text(_TWO_BRANCHES, encoding="utf-8")
    out = tmp_path / "baseline.json"
    assert main(["check", "--rule", _RULE, "--update-baseline", str(out), str(src)]) == 0
    capsys.readouterr()

    src.write_text(_THREE_BRANCHES, encoding="utf-8")

    assert main(["check", "--rule", _RULE, "--baseline", str(out), str(src)]) == 1
    reported = capsys.readouterr().out.strip().splitlines()
    assert len(reported) == 1
    assert "sandbox" in reported[0]


def test_removing_a_finding_does_not_bank_credit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "main.tf"
    src.write_text(_THREE_BRANCHES, encoding="utf-8")
    out = tmp_path / "baseline.json"
    assert main(["check", "--rule", _RULE, "--update-baseline", str(out), str(src)]) == 0
    capsys.readouterr()

    src.write_text(_TWO_BRANCHES, encoding="utf-8")
    assert main(["check", "--rule", _RULE, "--baseline", str(out), str(src)]) == 0
    assert not capsys.readouterr().out


def test_an_unreadable_baseline_is_an_operator_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "main.tf"
    src.write_text(_TWO_BRANCHES, encoding="utf-8")
    broken = tmp_path / "baseline.json"
    broken.write_text("{not json", encoding="utf-8")

    assert main(["check", "--rule", _RULE, "--baseline", str(broken), str(src)]) == 2
    assert "invalid baseline" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [[], ["check"], ["check", "missing.tf"], ["unknown"]],
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
    assert "sarj-iac-lint" in capsys.readouterr().out


def test_cli_repeated_rules_and_option_like_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "--source.tf").write_text("", encoding="utf-8")
    assert (
        main(
            [
                "check",
                "--rule",
                "require-deletion-protection",
                "--rule",
                "require-deletion-protection",
                "--",
                "--source.tf",
            ]
        )
        == 0
    )
