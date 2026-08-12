from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_iac_lint.__main__ import main, read_baseline


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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
    """The whole point: existing findings are grandfathered so only new ones fail."""
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
    """A baseline is a ceiling, not an allowance to re-spend elsewhere."""
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
