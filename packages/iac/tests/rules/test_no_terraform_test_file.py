from pathlib import Path

import pytest

from sarj_iac_lint.__main__ import analyze, apply_baseline, baseline_counts
from sarj_iac_lint.rules.no_terraform_test_file import NoTerraformTestFile


@pytest.mark.parametrize(
    "name",
    [
        "routing.tftest.hcl",
        "routing.tftest.json",
        "ROUTING.TFTEST.HCL",
        "verify-environment-boundary.test.mjs",
        "VERIFY-ENVIRONMENT-BOUNDARY.TEST.MJS",
        "verify-dev-apply-plan.jq",
        "VERIFY-DEV-APPLY-PLAN.JQ",
    ],
)
def test_flags_every_prohibited_iac_file_name(name: str) -> None:
    diagnostics = NoTerraformTestFile().check(Path(name), "# sarj-noqa: SARJ206\n")
    assert [(item.line, item.code, item.suppressible, item.baselineable) for item in diagnostics] == [
        (1, "SARJ206", False, False)
    ]


@pytest.mark.parametrize(
    "name",
    [
        "main.tf",
        "values.tfvars",
        "plan.json",
        "routing.hcl",
        "verify-environment-boundary.mjs",
        "verify-alert-policies.mjs",
        "inspect-dev-apply-plan.jq",
        "verify-dev-apply-plan.jq.bak",
        "my-verify-dev-apply-plan.jq",
        "verify-environment-boundary.test.js",
    ],
)
def test_allows_non_test_iac_files(name: str) -> None:
    assert NoTerraformTestFile().check(Path(name), 'resource "x" "y" {}\n') == []


def test_inline_suppression_cannot_bypass(tmp_path: Path) -> None:
    path = tmp_path / "routing.tftest.hcl"
    path.write_text('# sarj-noqa: SARJ206\nrun "routing" {}\n', encoding="utf-8")
    assert [item.code for item in analyze(["no-terraform-test-file"], [path])] == ["SARJ206"]


def test_baseline_cannot_bypass(tmp_path: Path) -> None:
    path = tmp_path / "routing.tftest.json"
    path.write_text("{}\n", encoding="utf-8")
    diagnostics = analyze(["no-terraform-test-file"], [path])
    assert apply_baseline(diagnostics, {str(path): {"SARJ206": 99}}) == diagnostics
    assert baseline_counts(diagnostics) == {}
