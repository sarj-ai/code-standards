from pathlib import Path

import pytest

from sarj_iac_lint.rules.no_terraform_data_condition import NoTerraformDataCondition


def _check(source: str, name: str = "main.tf"):
    return NoTerraformDataCondition().check(Path(name), source)


@pytest.mark.parametrize("condition", ["precondition", "postcondition"])
def test_rejects_lifecycle_conditions_on_terraform_data(condition: str) -> None:
    diagnostics = _check(
        'resource "terraform_data" "deployment_guard" {\n'
        "  lifecycle {\n"
        f"    {condition} {{\n"
        "      condition     = var.enabled\n"
        '      error_message = "deployment must be enabled"\n'
        "    }\n"
        "  }\n"
        "}\n"
    )

    assert [(item.code, item.line, item.col) for item in diagnostics] == [("SARJ210", 1, 1)]
    assert "terraform_data.deployment_guard" in diagnostics[0].message


def test_reports_one_diagnostic_for_multiple_conditions() -> None:
    diagnostics = _check(
        'resource "terraform_data" "guard" {\n'
        "  lifecycle {\n"
        "    precondition {\n"
        "      condition     = var.ready\n"
        '      error_message = "not ready"\n'
        "    }\n"
        "    postcondition {\n"
        "      condition     = self.output == null\n"
        '      error_message = "unexpected output"\n'
        "    }\n"
        "  }\n"
        "}\n"
    )

    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    "source",
    [
        'resource "terraform_data" "replacement" {\n  triggers_replace = [var.release]\n}\n',
        (
            'resource "google_storage_bucket" "records" {\n'
            "  lifecycle {\n"
            "    precondition {\n"
            '      condition     = var.location != ""\n'
            '      error_message = "location is required"\n'
            "    }\n"
            "  }\n"
            "}\n"
        ),
        (
            'variable "region" {\n'
            "  validation {\n"
            '    condition     = var.region != ""\n'
            '    error_message = "region is required"\n'
            "  }\n"
            "}\n"
        ),
        (
            'check "deployment" {\n'
            "  assert {\n"
            "    condition     = var.enabled\n"
            '    error_message = "deployment must be enabled"\n'
            "  }\n"
            "}\n"
        ),
        '# resource "terraform_data" "guard" { lifecycle { precondition {} } }\n',
        'locals { example = "resource terraform_data lifecycle precondition" }\n',
    ],
)
def test_allows_non_guard_patterns(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("name", ["main.tftest.hcl", "main.json", "main.yaml"])
def test_ignores_non_tf_files(name: str) -> None:
    source = 'resource "terraform_data" "guard" {\n  lifecycle {\n    precondition { condition = true }\n  }\n}\n'

    assert _check(source, name) == []


def test_malformed_hcl_does_not_crash() -> None:
    diagnostics = _check('resource "terraform_data" "guard" { lifecycle { precondition {')

    assert len(diagnostics) <= 1
