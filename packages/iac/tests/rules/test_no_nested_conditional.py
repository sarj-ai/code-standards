from __future__ import annotations

from pathlib import Path

import pytest

from sarj_iac_lint.__main__ import analyze
from sarj_iac_lint.rule_base import DefaultLevel
from sarj_iac_lint.rules.no_nested_conditional import NoNestedConditional


@pytest.mark.parametrize(
    "expression",
    [
        'var.primary ? "one" : var.secondary ? "two" : "three"',
        'var.primary ? (var.secondary ? "one" : "two") : "three"',
        'var.primary ? var.secondary ? "one" : "two" : "three"',
        '((var.primary ? "one" : (var.secondary ? "two" : "three")))',
    ],
)
def test_reports_nested_selection(expression: str) -> None:
    findings = NoNestedConditional().check(Path("main.tf"), f"locals {{\n  value = {expression}\n}}\n")

    assert len(findings) == 1
    assert (findings[0].line, findings[0].col) == (2, 3)
    assert findings[0].severity is DefaultLevel.WARNING


@pytest.mark.parametrize(
    "expression",
    [
        'var.primary ? "one" : "two"',
        'join("", [var.primary ? "one" : "two", var.secondary ? "three" : "four"])',
        '{ first = var.primary ? "one" : "two", second = var.secondary ? "three" : "four" }',
        '"literal ? question : text ? question : text"',
        'var.primary ? "literal ? question : text" : "two"',
        'var.primary ? join("", [var.secondary ? "one" : "two"]) : "three"',
        'var.config == null ? {} : { size = var.config.large ? "large" : "small" }',
        (
            "var.enabled ? merge(local.config, { entries = ["
            "for entry in local.entries : merge(entry, entry.active ? { selected = true } : {})"
            "] }) : local.config"
        ),
    ],
)
def test_preserves_independent_conditions_and_data(expression: str) -> None:
    source = f"locals {{\n  value = {expression}\n}}\n"

    assert NoNestedConditional().check(Path("main.tf"), source) == []


def test_checks_nested_blocks_once_and_preserves_comments() -> None:
    source = (
        'resource "example" "service" {\n'
        "  nested {\n"
        "    value = var.primary ? (\n"
        '      var.secondary ? "one" : "two" # nested selection\n'
        '    ) : "three"\n'
        "  }\n"
        "}\n"
    )

    findings = NoNestedConditional().check(Path("main.tf"), source)

    assert len(findings) == 1
    assert findings[0].line == 3


@pytest.mark.parametrize("path", ["fixtures/main.tf", "testdata/main.tf", "generated/main.tf", "test.tftest.hcl"])
def test_ignores_non_authored_terraform(path: str) -> None:
    source = 'locals { value = var.primary ? "one" : var.secondary ? "two" : "three" }\n'

    assert NoNestedConditional().check(Path(path), source) == []


def test_environment_policy_diagnostic_takes_precedence() -> None:
    source = 'locals { size = var.environment == "prod" ? "large" : var.secondary ? "medium" : "small" }\n'

    assert NoNestedConditional().check(Path("main.tf"), source) == []


def test_preserves_assertion_null_guards() -> None:
    source = (
        'variable "config" {\n'
        "  type = object({ enabled = bool, size = number })\n"
        "  validation {\n"
        "    condition = var.config == null ? true : var.config.enabled ? var.config.size > 0 : true\n"
        '    error_message = "Enabled configuration requires a positive size."\n'
        "  }\n"
        "}\n"
    )

    assert NoNestedConditional().check(Path("main.tf"), source) == []


def test_ignores_heredoc_data_and_malformed_structure() -> None:
    source = "locals {\n  text = <<DOC\na ? b : c ? d : e\nDOC\n}\n"

    assert NoNestedConditional().check(Path("main.tf"), source) == []
    assert NoNestedConditional().check(Path("main.tf"), "locals { value = a ? b : c ? d : e\n") == []


def test_warning_is_suppressible_at_attribute(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text(
        "locals {\n"
        '  value = var.primary ? "one" : var.secondary ? "two" : "three" # sarj-noqa: SARJ215 -- external contract\n'
        "}\n"
    )

    assert analyze(["no-nested-conditional"], [path]) == []
