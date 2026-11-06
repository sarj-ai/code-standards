from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_iac_lint.__main__ import analyze
from sarj_iac_lint.rule_base import DefaultLevel
from sarj_iac_lint.rules.no_boolean_enable_variable import NoBooleanEnableVariable


def test_documented_examples() -> None:
    verify_native_rule(NoBooleanEnableVariable, analyze)


@pytest.mark.parametrize(
    "name",
    [
        "keyless_storage_enabled",
        "enable_storage",
        "disable_storage",
        "storage_disabled",
        "enable",
        "enabled",
        "disable",
        "disabled",
    ],
)
def test_reports_boolean_switch_declaration(name: str) -> None:
    source = f'variable "{name}" {{\n  type = (bool)\n  default = false\n}}\n'

    findings = NoBooleanEnableVariable().check(Path("main.tf"), source)

    assert len(findings) == 1
    assert (findings[0].line, findings[0].col, findings[0].severity) == (1, 1, DefaultLevel.WARNING)


@pytest.mark.parametrize(
    "source",
    [
        'variable "enablement" { type = bool }',
        'variable "deletion_protection" { type = bool }',
        'variable "keyless_storage_enabled" { type = string }',
        'variable "enabled_regions" { type = list(string) }',
        'variable "config" { type = object({ enabled = bool }) }',
        'variable "storage_enabled" { default = false }',
        'resource "example" "storage_enabled" { enabled = true }',
        "locals { storage_enabled = true }",
        'module "storage" { source = "./storage"\n enabled = true }',
        '# variable "storage_enabled" { type = bool }',
        'locals { text = <<DOC\nvariable "storage_enabled" { type = bool }\nDOC\n}',
        'variable "storage_enabled" { type = bool',
    ],
)
def test_preserves_other_configuration_and_ignores_data(source: str) -> None:
    assert NoBooleanEnableVariable().check(Path("main.tf"), source) == []


@pytest.mark.parametrize("path", ["main.tf.json", "example.tftest.hcl", "values.tfvars", "main.yaml"])
def test_ignores_other_syntax(path: str) -> None:
    assert NoBooleanEnableVariable().check(Path(path), 'variable "enabled" { type = bool }') == []


def test_reports_each_variable_once_without_nested_attributes() -> None:
    source = 'variable "enabled" { type = bool\n validation { condition = var.enabled } }\nvariable "disable_app" { type = bool }'

    findings = NoBooleanEnableVariable().check(Path("main.tf"), source)

    assert [(finding.line, finding.col) for finding in findings] == [(1, 1), (3, 1)]


def test_warning_can_be_suppressed_at_the_declaration(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text(
        'variable "enable_paid_service" { # sarj-noqa: SARJ220 -- Optional billable capability\n type = bool\n}\n'
    )

    assert analyze([NoBooleanEnableVariable.id], [path]) == []
