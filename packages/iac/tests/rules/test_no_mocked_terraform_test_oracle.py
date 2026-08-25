from pathlib import Path

import pytest

from sarj_iac_lint.__main__ import analyze, apply_baseline
from sarj_iac_lint.rules.no_mocked_terraform_test_oracle import NoMockedTerraformTestOracle


@pytest.mark.parametrize(
    ("source", "line", "kind"),
    [
        ('mock_provider "aws" {}\n', 1, "mock_provider"),
        ('run "routing" {\n  override_module {\n    target = module.routing\n  }\n}\n', 2, "override_module"),
        ('mock_provider "aws" {\n  mock_data "aws_region" {}\n}\n', 1, "mock_provider"),
    ],
)
def test_flags_mock_and_override_blocks(source: str, line: int, kind: str) -> None:
    diagnostics = NoMockedTerraformTestOracle().check(Path("routing.tftest.hcl"), source)
    assert [(item.line, item.code, item.suppressible, item.baselineable) for item in diagnostics] == [
        (line, "SARJ206", True, True)
    ]
    assert kind in diagnostics[0].message


@pytest.mark.parametrize("command", ["plan", "apply"])
def test_allows_real_provider_terraform_tests(command: str) -> None:
    source = f'provider "aws" {{}}\nrun "routing" {{\n  command = {command}\n}}\n'
    assert NoMockedTerraformTestOracle().check(Path("routing.tftest.hcl"), source) == []


@pytest.mark.parametrize("name", ["main.tf", "values.tfvars", "plan.json", "routing.hcl"])
def test_allows_non_test_iac_files(name: str) -> None:
    source = 'mock_provider "aws" {}\n'
    assert NoMockedTerraformTestOracle().check(Path(name), source) == []


def test_ignores_mock_words_in_comments_strings_and_heredocs() -> None:
    source = """
# mock_provider "aws" {}
locals {
  label = "override_resource"
  script = <<SCRIPT
mock_data "aws_region" {}
SCRIPT
}
"""
    assert NoMockedTerraformTestOracle().check(Path("routing.tftest.hcl"), source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('{"mock_provider":{"aws":[{}]},"run":{"routing":[{}]}}', "mock_provider"),
        ('{"run":{"routing":[{"override_data":[{"target":"data.aws_region.current"}]}]}}', "override_data"),
        ('{"run":{"routing":[{"variables":{"mock_data":"business-value"}}]}}', None),
    ],
)
def test_understands_json_test_structure(source: str, expected: str | None) -> None:
    diagnostics = NoMockedTerraformTestOracle().check(Path("routing.tftest.json"), source)
    assert len(diagnostics) == (expected is not None)
    if expected is not None:
        assert expected in diagnostics[0].message


def test_inline_suppression_documents_exception(tmp_path: Path) -> None:
    path = tmp_path / "routing.tftest.hcl"
    path.write_text('mock_provider "aws" {} # sarj-noqa: SARJ206\n', encoding="utf-8")
    assert analyze(["no-mocked-terraform-test-oracle"], [path]) == []


def test_baseline_can_ratchet_existing_finding(tmp_path: Path) -> None:
    path = tmp_path / "routing.tftest.json"
    path.write_text('{"mock_provider":{"aws":[{}]}}\n', encoding="utf-8")
    diagnostics = analyze(["no-mocked-terraform-test-oracle"], [path])
    assert apply_baseline(diagnostics, {str(path): {"SARJ206": 1}}) == []
