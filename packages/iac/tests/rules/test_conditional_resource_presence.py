from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_iac_lint.__main__ import analyze, apply_baseline, baseline_counts, main
from sarj_iac_lint.autofix import fix_source
from sarj_iac_lint.rule_base import AutofixPolicy, DefaultLevel
from sarj_iac_lint.rules.conditional_resource_presence import ConditionalResourcePresence


@pytest.mark.parametrize(
    ("attribute", "expression"),
    [
        ("count", "var.enabled ? 1 : 0"),
        ("count", "var.enabled ? 0 : 1"),
        ("count", "var.enabled ? var.replicas : 0"),
        ("count", "var.enabled ? 0.0 : 2"),
        ("count", 'var.enabled ? "0" : "1"'),
        ("count", "((var.enabled ? (1) : (0)))"),
        ("count", "var.enabled ? (var.secondary ? 1 : 0) : 0"),
        ("count", "tonumber(var.enabled ? 1 : 0)"),
        ("count", "length(var.enabled ? [1] : [])"),
        ("count", "true ? 1 : 0"),
        ("for_each", "var.enabled ? { primary = true } : {}"),
        ("for_each", "var.enabled ? {} : var.targets"),
        ("for_each", 'var.enabled ? toset(["primary"]) : toset([])'),
        ("for_each", 'toset(var.enabled ? ["primary"] : [])'),
        ("for_each", "tomap(var.enabled ? var.targets : {})"),
        ("for_each", 'var.mode != "shared" ? { primary = true } : {}'),
    ],
)
def test_warns_on_conditional_presence(attribute: str, expression: str) -> None:
    source = f'resource "example_service" "this" {{\n  {attribute} = {expression}\n}}\n'
    findings = ConditionalResourcePresence().check(Path("main.tf"), source)

    assert len(findings) == 1
    assert (findings[0].line, findings[0].col) == (2, 3)
    assert findings[0].severity is DefaultLevel.WARNING


@pytest.mark.parametrize(
    ("attribute", "expression"),
    [
        ("count", "var.replicas"),
        ("count", "2"),
        ("count", "0"),
        ("count", "var.enabled ? 1 : 2"),
        ("count", "var.enabled ? 0 : 0"),
        ("count", "length(var.targets)"),
        ("count", "local.unknown"),
        ("count", 'length("literal ? 1 : 0")'),
        ("for_each", "var.targets"),
        ("for_each", "{}"),
        ("for_each", "var.enabled ? {} : {}"),
        ("for_each", "var.primary ? var.primary_targets : var.secondary_targets"),
        ("for_each", "{ for key, value in var.targets : key => value if value.enabled }"),
        ("value", "var.enabled ? 1 : 0"),
    ],
)
def test_preserves_multiplicity_and_ordinary_selection(attribute: str, expression: str) -> None:
    source = f'resource "example_service" "this" {{\n  {attribute} = {expression}\n}}\n'

    assert ConditionalResourcePresence().check(Path("main.tf"), source) == []


@pytest.mark.parametrize("header", ['module "service"', 'ephemeral "example_service" "this"'])
def test_handles_other_managed_instance_blocks(header: str) -> None:
    source = f"{header} {{\n  count = var.enabled ? 1 : 0\n}}\n"

    assert len(ConditionalResourcePresence().check(Path("main.tf"), source)) == 1


@pytest.mark.parametrize("header", ['data "example_service" "this"', "locals", 'provider "example"'])
def test_does_not_infer_provisioning_in_other_blocks(header: str) -> None:
    source = f"{header} {{\n  count = var.enabled ? 1 : 0\n}}\n"

    assert ConditionalResourcePresence().check(Path("main.tf"), source) == []


def test_follows_same_file_local_aliases_once_at_the_consumer() -> None:
    source = (
        "locals {\n  selected = local.actual\n  actual = var.enabled ? 1 : 0\n}\n"
        'resource "example_service" "this" {\n  count = local.selected\n}\n'
    )
    findings = ConditionalResourcePresence().check(Path("main.tf"), source)

    assert len(findings) == 1
    assert findings[0].line == 6


@pytest.mark.parametrize(
    "locals_source",
    ["locals { a = local.b\n b = local.a }", "locals { a = local.missing }"],
)
def test_unresolved_or_cyclic_aliases_are_not_guessed(locals_source: str) -> None:
    source = locals_source + '\nresource "example_service" "this" { count = local.a }\n'

    assert ConditionalResourcePresence().check(Path("main.tf"), source) == []


@pytest.mark.parametrize("path", ["fixtures/main.tf", "testdata/main.tf", "generated/main.tf", "main.tf.json", "x.hcl"])
def test_non_authored_or_other_dialects_are_excluded(path: str) -> None:
    source = 'resource "example_service" "this" { count = var.enabled ? 1 : 0 }\n'

    assert ConditionalResourcePresence().check(Path(path), source) == []


@pytest.mark.parametrize(
    "source",
    [
        '# resource "example_service" "this" { count = var.enabled ? 1 : 0 }\n',
        'locals { text = "count = var.enabled ? 1 : 0" }\n',
        'locals { text = <<DOC\nresource "example_service" "this" { count = x ? 1 : 0 }\nDOC\n}\n',
        '# Generated; do not edit\nresource "example_service" "this" { count = x ? 1 : 0 }\n',
        'resource "example_service" "this" { count = x ? 1 : 0\n',
    ],
)
def test_ignores_data_generated_headers_and_malformed_hcl(source: str) -> None:
    assert ConditionalResourcePresence().check(Path("main.tf"), source) == []


def test_specific_environment_policy_takes_precedence(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text('resource "example_service" "this" { count = var.environment == "prod" ? 1 : 0 }\n')

    findings = analyze(["conditional-resource-presence", "no-environment-conditional"], [path])

    assert [finding.code for finding in findings] == ["SARJ204"]


def test_presence_warning_takes_precedence_over_nested_selection(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text('resource "example_service" "this" { count = var.a ? 1 : var.b ? 1 : 0 }\n')

    findings = analyze(["conditional-resource-presence", "no-nested-conditional"], [path])

    assert [finding.code for finding in findings] == ["SARJ221"]


def test_exact_code_suppression_remains_local(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text(
        'resource "example_service" "this" {\n count = x ? 1 : 0 # sarj-noqa: SARJ221 -- optional provider\n}\n'
    )

    assert analyze(["conditional-resource-presence"], [path]) == []


def test_documented_examples_and_manual_only_fix_policy() -> None:
    spec = ConditionalResourcePresence.native_spec()
    assert spec is not None
    assert spec.default_level is DefaultLevel.WARNING
    assert spec.autofix is AutofixPolicy.NONE
    verify_native_rule(ConditionalResourcePresence, analyze)
    source = 'resource "example_service" "this" { count = var.enabled ? 1 : 0 }\n'
    assert fix_source(Path("main.tf"), source, rule_ids=["conditional-resource-presence"]) == source


def test_warning_is_nonblocking_and_not_erased_by_an_error_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "main.tf"
    path.write_text('resource "example_service" "this" { count = var.enabled ? 1 : 0 }\n')

    assert main(["check", "--rule", "conditional-resource-presence", str(path)]) == 0
    assert "SARJ221 warning:" in capsys.readouterr().out
    findings = analyze(["conditional-resource-presence"], [path])
    assert baseline_counts(findings) == {}
    assert apply_baseline(findings, {str(path): {"SARJ221": 1}}) == findings


def test_justification_does_not_require_terraform_comments(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text(
        'variable "enabled" {\n type = bool\n description = "Optional customer-managed integration; reviewed in the owning PR."\n}\n'
        'resource "example_service" "this" { count = var.enabled ? 1 : 0 }\n'
    )

    findings = analyze(["conditional-resource-presence", "no-terraform-comments"], [path])

    assert [finding.code for finding in findings] == ["SARJ221"]


def test_physical_crlf_location_and_unicode_are_preserved() -> None:
    source = 'locals { label = "雪" }\r\nresource "example_service" "this" {\r\n  count = var.enabled ? 1 : 0\r\n}\r\n'
    findings = ConditionalResourcePresence().check(Path("main.tf"), source)

    assert len(findings) == 1
    assert (findings[0].line, findings[0].col) == (3, 3)
