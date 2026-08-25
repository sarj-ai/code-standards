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


def test_directory_scan_includes_bespoke_iac_verifier_suffixes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scripts = tmp_path / "iac" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "verify-environment-boundary.test.mjs").write_text("export {};\n", encoding="utf-8")
    (scripts / "verify-dev-apply-plan.jq").write_text(".resource_changes\n", encoding="utf-8")

    assert main(["check", "--rule", "no-terraform-test-file", str(tmp_path)]) == 1
    reported = capsys.readouterr().out
    assert "verify-environment-boundary.test.mjs" in reported
    assert "verify-dev-apply-plan.jq" in reported


def test_large_prohibited_verifier_is_checked_without_reading_its_contents(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "verify-dev-apply-plan.jq"
    source.write_bytes(b"x" * 500_001)

    assert main(["check", "--rule", "no-terraform-test-file", str(tmp_path)]) == 1
    assert "verify-dev-apply-plan.jq" in capsys.readouterr().out


def test_overlapping_explicit_and_directory_inputs_report_a_prohibited_file_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "verify-dev-apply-plan.jq"
    source.write_text(".resource_changes\n", encoding="utf-8")

    assert main(["check", "--rule", "no-terraform-test-file", str(source), str(tmp_path)]) == 1
    reported = capsys.readouterr().out.strip().splitlines()
    assert len(reported) == 1


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
