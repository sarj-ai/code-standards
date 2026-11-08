from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_iac_lint.__main__ import analyze, main
from sarj_iac_lint.autofix import fix_source
from sarj_iac_lint.rule_base import DefaultLevel, Diagnostic, RuleDocumentation
from sarj_iac_lint.rules.no_terraform_guard_blocks import NoTerraformGuardBlocks


def test_documented_examples() -> None:
    verify_native_rule(NoTerraformGuardBlocks, analyze)


@pytest.mark.parametrize(
    ("owner", "guard"),
    [
        ('variable "enabled"', "validation"),
        ('output "endpoint"', "precondition"),
        ('resource "example_service" "app"', "lifecycle { precondition"),
        ('resource "example_service" "app"', "lifecycle { postcondition"),
        ('data "example_image" "selected"', "lifecycle { precondition"),
        ('data "example_image" "selected"', "lifecycle { postcondition"),
        ('ephemeral "example_secret" "temporary"', "lifecycle { precondition"),
        ('ephemeral "example_secret" "temporary"', "lifecycle { postcondition"),
        ('resource "terraform_data" "operation"', "lifecycle { precondition"),
    ],
)
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_rejects_each_terraform_guard_owner(owner: str, guard: str, ending: str) -> None:
    source = f'{owner} {{\n  {guard} {{\n    condition = var.ready\n    error_message = "Require readiness."\n  }}\n'
    source += "}\n" if guard.startswith("lifecycle") else ""
    source += "}\n"

    findings = _check(source.replace("\n", ending))

    assert [(finding.code, finding.line, finding.col) for finding in findings] == [
        (NoTerraformGuardBlocks.code, 2, 3 if guard in {"validation", "precondition"} else 15)
    ]


def test_check_with_nested_conditions_reports_once() -> None:
    source = """check "deployment" {
  data "http" "ready" {
    lifecycle {
      postcondition {
        condition = self.status_code == 200
        error_message = "Require a successful response."
      }
    }
  }
  assert {
    condition = var.ready
    error_message = "Require readiness."
  }
  assert {
    condition = var.healthy
    error_message = "Require health."
  }
}
"""

    assert [(finding.line, finding.col) for finding in _check(source)] == [(1, 1)]


def test_reports_each_variable_validation() -> None:
    source = """variable "replicas" {
  type = number
  validation {
    condition = var.replicas > 0
    error_message = "Require a positive count."
  }
  validation {
    condition = var.replicas < 100
    error_message = "Respect capacity."
  }
}
"""

    assert [finding.line for finding in _check(source)] == [3, 7]


@pytest.mark.parametrize(
    "source",
    [
        'variable "ready" { type = bool }\n',
        'resource "example_service" "app" {\n  count = var.enabled ? 1 : 0\n}\n',
        'resource "example_service" "app" {\n  for_each = var.enabled ? var.services : {}\n}\n',
        'resource "example_service" "app" { lifecycle { prevent_destroy = true } }\n',
        'resource "example_service" "app" { lifecycle { ignore_changes = [labels] } }\n',
        'resource "example_service" "app" { deletion_protection = true }\n',
        'ephemeral "example_secret" "temporary" { name = var.secret_name }\n',
        'resource "example_iam_binding" "member" { condition { expression = var.expression } }\n',
        'resource "example_service" "app" { validation { expression = var.expression } }\n',
        'resource "example_service" "app" { check { expression = var.expression } }\n',
        "locals { policy = { validation = { condition = true }, precondition = {}, check = {} } }\n",
        'locals { example = "validation { condition = true }" }\n',
        'locals { example = <<TEXT\ncheck "ready" { assert { condition = true } }\nTEXT\n}\n',
        '# check "ready" { assert { condition = true } }\n',
        '/* variable "ready" { validation { condition = true } } */\n',
        'resource "example_service" "app" { lifecycle { precondition "provider_label" {} } }\n',
    ],
)
def test_preserves_branching_provider_payloads_and_native_protection(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("name", ["main.tftest.hcl", "terragrunt.hcl", "main.tf.json", "main.yaml"])
def test_other_dialects_are_outside_the_rule(name: str) -> None:
    assert NoTerraformGuardBlocks().check(Path(name), 'check "ready" { assert { condition = true } }\n') == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [('variable "ready" { validation {', 1), ('check "ready" { assert {', 1), ('locals { text = "unfinished', 0)],
)
def test_malformed_source_preserves_shared_parser_recovery(source: str, expected: int) -> None:
    assert len(_check(source)) == expected


def test_no_automatic_deletion_and_cli_uses_authored_severity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "main.tf"
    source = 'variable "ready" { validation { condition = var.ready } }\n'
    path.write_text(source)

    assert fix_source(path, source, rule_ids=[NoTerraformGuardBlocks.id]) == source
    expected = int(_documentation().default_level is DefaultLevel.ERROR)
    assert main(["check", "--rule", NoTerraformGuardBlocks.id, "--fix", str(path)]) == expected
    assert NoTerraformGuardBlocks.code in capsys.readouterr().out
    assert path.read_text() == source


@pytest.mark.parametrize("level", [DefaultLevel.WARNING, DefaultLevel.ERROR])
def test_narrower_checks_survive_warning_stage_and_are_deduplicated_after_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: DefaultLevel
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Authored class-level severity lookup is the precedence behavior under test.
        NoTerraformGuardBlocks, "documentation", replace(_documentation(), default_level=level)
    )
    path = tmp_path / "main.tf"
    path.write_text(
        'variable "value" {\n  type = string\n  validation {\n    condition = can(tostring(var.value))\n    error_message = "Require a string."\n  }\n}\n'
    )

    findings = analyze([NoTerraformGuardBlocks.id, "no-redundant-variable-validation"], [path])

    expected = (
        [NoTerraformGuardBlocks.code] if level is DefaultLevel.ERROR else [NoTerraformGuardBlocks.code, "SARJ209"]
    )
    assert [finding.code for finding in findings] == expected


def test_suppressing_the_broad_ban_does_not_suppress_a_narrower_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Authored class-level severity lookup is the suppression behavior under test.
        NoTerraformGuardBlocks,
        "documentation",
        replace(_documentation(), default_level=DefaultLevel.ERROR),
    )
    path = tmp_path / "main.tf"
    path.write_text(
        f'variable "value" {{\n  type = string\n  validation {{ # sarj-noqa: {NoTerraformGuardBlocks.code} -- staged exception\n    condition = can(tostring(var.value))\n    error_message = "Require a string."\n  }}\n}}\n'
    )

    assert [
        finding.code for finding in analyze([NoTerraformGuardBlocks.id, "no-redundant-variable-validation"], [path])
    ] == ["SARJ209"]


def test_promoted_ban_deduplicates_fake_resource_guards_and_retains_other_expression_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Authored class-level severity lookup is the precedence behavior under test.
        NoTerraformGuardBlocks,
        "documentation",
        replace(_documentation(), default_level=DefaultLevel.ERROR),
    )
    path = tmp_path / "main.tf"
    predicate = " && ".join(f"var.{letter} > 0" for letter in "abcdefg")
    path.write_text(
        f'resource "terraform_data" "guard" {{\n  lifecycle {{\n    precondition {{\n      condition = {predicate}\n      error_message = "Require readiness."\n    }}\n  }}\n}}\nlocals {{\n  value = {predicate}\n}}\n'
    )

    findings = analyze([NoTerraformGuardBlocks.id, "no-terraform-data-condition", "expression-complexity"], [path])

    assert [(finding.code, finding.line) for finding in findings] == [(NoTerraformGuardBlocks.code, 3), ("SARJ217", 10)]


@pytest.mark.parametrize(
    "uncovered",
    [
        'resource "terraform_data" "exception" {\n  lifecycle {\n    precondition { # sarj-noqa: SARJ222 -- staged exception\n      condition = var.ready\n    }\n  }\n}\n',
        'resource "terraform_data" "invalid_label" {\n  lifecycle {\n    precondition "extra_label" { condition = var.ready }\n  }\n}\n',
        'resource "terraform_data" {\n  lifecycle {\n    precondition { condition = var.ready }\n  }\n}\n',
    ],
)
def test_guard_precedence_preserves_uncovered_resource_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uncovered: str
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Authored class-level severity lookup is the precedence behavior under test.
        NoTerraformGuardBlocks,
        "documentation",
        replace(_documentation(), default_level=DefaultLevel.ERROR),
    )
    path = tmp_path / "main.tf"
    path.write_text(
        'resource "terraform_data" "banned" {\n  lifecycle {\n    precondition { condition = var.ready }\n  }\n}\n'
        + uncovered
    )

    findings = analyze([NoTerraformGuardBlocks.id, "no-terraform-data-condition"], [path])

    assert [(finding.code, finding.line) for finding in findings] == [(NoTerraformGuardBlocks.code, 3), ("SARJ210", 6)]


def _check(source: str) -> list[Diagnostic]:
    return NoTerraformGuardBlocks().check(Path("main.tf"), source)


def _documentation() -> RuleDocumentation:
    documentation = NoTerraformGuardBlocks.documentation
    assert documentation is not None
    return documentation
