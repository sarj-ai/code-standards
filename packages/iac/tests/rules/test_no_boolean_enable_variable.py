from datetime import date
import json
from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_iac_lint.__main__ import analyze, apply_baseline, main
from sarj_iac_lint.autofix import fix_source
from sarj_iac_lint.rule_base import DefaultLevel
from sarj_iac_lint.rules.no_boolean_enable_variable import NoBooleanEnableVariable


_TODAY = date(2026, 11, 8)
_REMOVAL = "Remove when: Every environment uses the new route; delete the input and legacy route."


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
        "use_new_route",
        "keep_legacy",
        "enablement",
        "deletion_protection",
    ],
)
def test_reports_boolean_switch_declaration(name: str) -> None:
    source = f'variable "{name}" {{\n  type = (bool)\n  default = false\n}}\n'

    findings = NoBooleanEnableVariable().check(Path("main.tf"), source)

    assert len(findings) == 1
    assert (findings[0].line, findings[0].col, findings[0].severity) == (1, 1, DefaultLevel.ERROR)


@pytest.mark.parametrize(
    "source",
    [
        'variable "enablement" {\n type = bool\n description = "Permanent: Callers choose whether to run this optional capability."\n}',
        'variable "deletion_protection" {\n type = bool\n description = "Permanent: Explicit operator control over destructive operations."\n}',
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


def test_exact_code_suppression_at_the_declaration(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text(
        'variable "enable_paid_service" { # sarj-noqa: SARJ220 -- Optional billable capability\n type = bool\n}\n'
    )

    assert analyze([NoBooleanEnableVariable.id], [path]) == []


@pytest.mark.parametrize(
    "description",
    [
        "Permanent: Production pages on-call; previews keep paging off.",
        "Permanent: Customers can independently opt out of this paid capability.",
        f"Retire by: 2026-11-09\n{_REMOVAL}",
        f"Retire by: 2026-11-08\n{_REMOVAL}",
        f"Route migration.\nRetire by: 2026-11-30\n{_REMOVAL}",
        f"retire BY: 2026-11-30\n{_REMOVAL.lower()}",
        f"Retire by: 2028-02-29\n{_REMOVAL}",
    ],
)
def test_accepts_explicit_lifecycle(description: str) -> None:
    source = f'variable "route_enabled" {{\n type = bool\n description = {json.dumps(description)}\n}}\n'

    assert NoBooleanEnableVariable(today=_TODAY).check(Path("main.tf"), source) == []


@pytest.mark.parametrize(
    ("description", "message"),
    [
        ("Temporary gate until all deployments migrate.", "no lifecycle"),
        ("Retire by: soon\n" + _REMOVAL, "YYYY-MM-DD"),
        ("Retire by: 2026-2-01\n" + _REMOVAL, "YYYY-MM-DD"),
        ("Retire by: 2026-02-30\n" + _REMOVAL, "valid calendar date"),
        ("Retire by: 2025-02-29\n" + _REMOVAL, "valid calendar date"),
        ("Retire by: 0000-01-01\n" + _REMOVAL, "valid calendar date"),
        ("Retire by: 2026-11-07\n" + _REMOVAL, "expired after 2026-11-07 UTC"),
        ("Retire by: 2026-11-30T23:59:59Z\n" + _REMOVAL, "YYYY-MM-DD"),
        ("Retire by: ２０２６-１１-３０\n" + _REMOVAL, "YYYY-MM-DD"),
        ("Retire by: 20261130\n" + _REMOVAL, "YYYY-MM-DD"),
        ("Retire by: 2026-366\n" + _REMOVAL, "YYYY-MM-DD"),
        ("Retire by: 2026-11-30", "Remove when:"),
        ("Retire by: 2026-11-30\nRemove when: ", "Remove when:"),
        ("Retire by: 2026-11-30\n" + _REMOVAL + "\n" + _REMOVAL, "exactly one"),
        ("Retire by: 2026-11-30\n" + _REMOVAL + "\nRemove when:", "exactly one"),
        ("Permanent:", "no rationale"),
        ("Permanent: \t ", "no rationale"),
        ("Permanent: Different paging policies.\n" + _REMOVAL, "also declares a removal"),
        ("Permanent: Different paging policies.\nRetire by: 2026-11-30\n" + _REMOVAL, "conflicting"),
        ("Retire by: 2026-11-30\nRetire by: 2026-11-30\n" + _REMOVAL, "duplicated"),
        ("Permanent: Different paging policies.\nPermanent: Another rationale.", "duplicated"),
    ],
)
def test_reports_invalid_lifecycle_once(description: str, message: str) -> None:
    source = f'variable "route_enabled" {{\n type = bool\n description = {json.dumps(description)}\n}}\n'

    findings = NoBooleanEnableVariable(today=_TODAY).check(Path("main.tf"), source)

    assert len(findings) == 1
    assert message in findings[0].message
    assert (findings[0].line, findings[0].col) == (1, 1)


@pytest.mark.parametrize("default", ["true", "false"])
def test_enabling_a_flag_does_not_retire_it(default: str) -> None:
    source = (
        'variable "route_enabled" {\n type = bool\n'
        f' default = {default}\n description = "Retire by: 2026-11-07\\n{_REMOVAL}"\n}}\n'
    )

    findings = NoBooleanEnableVariable(today=_TODAY).check(Path("main.tf"), source)

    assert len(findings) == 1
    assert "expired" in findings[0].message


def test_clock_is_read_per_check_instead_of_caching_results_by_source() -> None:
    source = f'variable "route_enabled" {{\n type = bool\n description = "Retire by: 2026-11-08\\n{_REMOVAL}"\n}}\n'

    assert NoBooleanEnableVariable(today=_TODAY).check(Path("main.tf"), source) == []
    assert len(NoBooleanEnableVariable(today=date(2026, 11, 9)).check(Path("main.tf"), source)) == 1


@pytest.mark.parametrize("marker", ["<<DOC", "<<-DOC"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_literal_heredoc_description(marker: str, newline: str) -> None:
    source = (
        'variable "route_enabled" {\n  type = bool\n'
        f"  description = {marker}\n    Retire by: 2026-11-30\n    {_REMOVAL}\nDOC\n}}\n"
    ).replace("\n", newline)

    assert NoBooleanEnableVariable(today=_TODAY).check(Path("main.tf"), source) == []


@pytest.mark.parametrize(
    "description",
    [
        '"Permanent: ${var.reason}"',
        '"Permanent: %{ if true }routing%{ endif }"',
        "<<DOC\nPermanent: ${var.reason}\nDOC",
        "<<DOC\nPermanent: %{ if true }routing%{ endif }\nDOC",
        "var.lifecycle_description",
    ],
)
def test_dynamic_description_does_not_bypass_lifecycle(description: str) -> None:
    source = f'variable "route_enabled" {{\n type = bool\n description = {description}\n}}\n'

    findings = NoBooleanEnableVariable(today=_TODAY).check(Path("main.tf"), source)

    assert len(findings) == 1
    assert "no lifecycle" in findings[0].message


@pytest.mark.parametrize(
    "description",
    [
        '"Permanent: $${upstream} controls this independently."',
        "<<DOC\nPermanent: %%{upstream} controls this independently.\nDOC",
    ],
)
def test_escaped_template_markers_are_literal(description: str) -> None:
    source = f'variable "route_enabled" {{\n type = bool\n description = {description}\n}}\n'

    assert NoBooleanEnableVariable(today=_TODAY).check(Path("main.tf"), source) == []


@pytest.mark.parametrize(
    "contents",
    [
        'description = "A route gate."\n# Permanent: Different paging policies.',
        'validation {\n condition = true\n error_message = "Permanent: Different paging policies."\n}',
        'description = "Permanent: Different paging policies."\n description = "Duplicate attribute."',
    ],
)
def test_comments_nested_attributes_and_duplicate_descriptions_do_not_satisfy_policy(contents: str) -> None:
    source = f'variable "route_enabled" {{\n type = bool\n {contents}\n}}\n'

    assert len(NoBooleanEnableVariable(today=_TODAY).check(Path("main.tf"), source)) == 1


@pytest.mark.parametrize("type_name", ["string", "bool", "number", "object({ phase = string })"])
def test_explicit_lifecycle_on_other_inputs_is_still_checked(type_name: str) -> None:
    source = (
        f'variable "migration_phase" {{\n type = {type_name}\n description = "Retire by: 2026-11-07\\n{_REMOVAL}"\n}}\n'
    )

    findings = NoBooleanEnableVariable(today=_TODAY).check(Path("main.tf"), source)

    assert len(findings) == 1
    assert "expired" in findings[0].message


def test_unrelated_sibling_lifecycle_does_not_exempt_a_switch() -> None:
    source = (
        'variable "paging_enabled" {\n type = bool\n description = "Permanent: Environments page independently."\n}\n'
        'variable "route_enabled" { type = bool }\n'
    )

    findings = NoBooleanEnableVariable(today=_TODAY).check(Path("main.tf"), source)

    assert len(findings) == 1
    assert findings[0].line == 5


def test_generated_switches_need_lifecycle_from_the_generator() -> None:
    source = '# Code generated. DO NOT EDIT.\nvariable "route_enabled" { type = bool }\n'

    assert len(NoBooleanEnableVariable(today=_TODAY).check(Path("main.tf"), source)) == 1


def test_diagnostics_never_echo_description_contents() -> None:
    source = 'variable "route_enabled" {\n type = bool\n description = "PRIVATE_PLACEHOLDER"\n}\n'

    findings = NoBooleanEnableVariable(today=_TODAY).check(Path("main.tf"), source)

    assert len(findings) == 1
    assert "PRIVATE_PLACEHOLDER" not in findings[0].message


def test_expired_lifecycle_cannot_be_hidden_by_a_count_baseline() -> None:
    path = Path("main.tf")
    source = f'variable "route_enabled" {{\n type = bool\n description = "Retire by: 2026-11-07\\n{_REMOVAL}"\n}}\n'
    findings = NoBooleanEnableVariable(today=_TODAY).check(path, source)

    remaining = apply_baseline(findings, {"main.tf": {"SARJ220": 100}}, root=Path.cwd())

    assert len(remaining) == 1
    assert remaining[0].baselineable is False


@pytest.mark.parametrize(
    ("description", "status"),
    [
        ("A migration switch.", 1),
        ("Retire by: 2000-01-01\n" + _REMOVAL, 1),
        ("Retire by: 2099-12-31\n" + _REMOVAL, 0),
        ("Permanent: Environments independently control paging.", 0),
    ],
)
def test_cli_enforces_lifecycle(tmp_path: Path, description: str, status: int) -> None:
    path = tmp_path / "main.tf"
    path.write_text(f'variable "route_enabled" {{\n type = bool\n description = {json.dumps(description)}\n}}\n')

    assert main(["check", "--rule", NoBooleanEnableVariable.id, str(path)]) == status


def test_lifecycle_enforcement_never_automatically_removes_a_resource_gate() -> None:
    source = (
        'variable "route_enabled" { type = bool }\n'
        'resource "example_route" "private" { count = var.route_enabled ? 1 : 0 }\n'
    )

    assert fix_source(Path("main.tf"), source, rule_ids=[NoBooleanEnableVariable.id]) == source


def test_description_metadata_is_compatible_with_no_comment_policy(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text(
        'variable "paging_enabled" {\n type = bool\n description = "Permanent: Environments page independently."\n}\n'
    )

    assert analyze([NoBooleanEnableVariable.id, "no-terraform-comments"], [path]) == []
