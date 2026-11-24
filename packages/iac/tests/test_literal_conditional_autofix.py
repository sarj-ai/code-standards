from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from sarj_iac_lint.__main__ import main
from sarj_iac_lint.autofix import fix_source
from sarj_iac_lint.declaration_fixes import consolidate_declarations
from sarj_iac_lint.json_boundary import is_object_mapping, parse_json
from sarj_iac_lint.rules.no_nested_conditional import NoNestedConditional
from sarj_iac_lint.rules.no_redundant_variable_validation import NoRedundantVariableValidation


_CLOSED_CASES = [
    ('true ? "large" : false ? "medium" : "small"', '"large"'),
    ('false ? "large" : false ? "medium" : "small"', '"small"'),
    ('true ? (false ? "left" : "right") : "last"', '"right"'),
    ('((false ? (true ? "left" : "right") : "last"))', '"last"'),
    ("true ? false : false ? true : false", "false"),
    ("false ? false : true ? true : false", "true"),
    ("true ? 12.5 : false ? 0.25 : 3.5", "12.5"),
    ("false ? 12 : true ? 2.5e+2 : 0.01", "2.5e+2"),
    ("(false) ? 12 : (true) ? -1.25e-2 : 0", "-1.25e-2"),
    ('true ? "snow ☃ ? :" : false ? "百分%" : "$literal"', '"snow ☃ ? :"'),
]


@pytest.mark.parametrize(
    ("expression", "expected"), [("true ? 1 : 0", "1"), ("false ? 1 : 0", "0"), ("true ? (false ? 2 : 3) : 0", "3")]
)
@pytest.mark.parametrize("kind", ["resource", "module", "ephemeral"])
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_literal_count_fixes_retain_the_attribute_addresses_and_other_content(
    expression: str, expected: str, kind: str, ending: str
) -> None:
    labels = '"child"' if kind == "module" else '"terraform_data" "this"'
    source = f"{kind} {labels} {{\n  count = {expression}\n}}\n".replace("\n", ending)
    fixed = fix_source(Path("main.tf"), source, rule_ids=["conditional-resource-presence"])
    assert fixed == source.replace(expression, expected)
    assert fix_source(Path("main.tf"), fixed, rule_ids=["conditional-resource-presence"]) == fixed


@pytest.mark.parametrize(
    "expression",
    [
        "var.enabled ? 1 : 0",
        'true ? 1 : "0"',
        "true ? 1.5 : 0",
        'true ? 1 : tonumber("0")',
        "true ? -1 : 0",
        "true ? null : 0",
    ],
)
def test_count_fix_refuses_unproved_types_inputs_and_invalid_selected_counts(expression: str) -> None:
    source = f'resource "terraform_data" "this" {{\n  count = {expression}\n}}\n'
    assert fix_source(Path("main.tf"), source, rule_ids=["conditional-resource-presence"]) == source


def test_count_and_empty_comment_fixes_converge_together() -> None:
    source = 'resource "terraform_data" "this" {\n  count = true ? 1 : 0 #\n}\n'
    rules = ["conditional-resource-presence", "no-terraform-comments"]
    fixed = fix_source(Path("main.tf"), source, rule_ids=rules)
    assert "count = 1" in fixed
    assert "?" not in fixed
    assert fix_source(Path("main.tf"), fixed, rule_ids=rules) == fixed


def test_for_each_and_dated_default_flags_remain_reviewed() -> None:
    source = 'variable "enabled" {\n  type = bool\n  default = true\n  description = "Retire by: 2000-01-01\\nRemove when: Reviewed cutover."\n}\nmodule "child" {\n  source = "./child"\n  count = var.enabled ? 1 : 0\n}\nresource "terraform_data" "this" {\n  for_each = true ? { kept = 1 } : {}\n}\n'
    assert fix_source(Path("main.tf"), source, rule_ids=["conditional-resource-presence"]) == source


@pytest.mark.parametrize(("expression", "expected"), _CLOSED_CASES)
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_closed_literal_selections_preserve_other_source_and_converge(
    expression: str, expected: str, ending: str
) -> None:
    source = ending.join(("locals {", '  retained = "owned"', f"  value = {expression}  ", "}", ""))
    expected_source = source.replace(f"  value = {expression}  ", f"  value = {expected}  ")
    path = Path("main.tf")
    assert len(NoNestedConditional().check(path, source)) == 1

    fixed = fix_source(path, source, rule_ids=["no-nested-conditional"])

    assert fixed == expected_source
    assert NoNestedConditional().check(path, fixed) == []
    assert fix_source(path, fixed, rule_ids=["no-nested-conditional"]) == fixed


@pytest.mark.parametrize(
    "expression",
    [
        'var.enabled ? "one" : true ? "two" : "three"',
        'true ? "one" : var.enabled ? "two" : "three"',
        'true ? "one" : false ? "two" : missing.value',
        'true ? "one" : false ? "two" : file("missing")',
        'true ? 12 : false ? "two" : "three"',
        "true ? null : false ? 2 : 3",
        "true ? true : false ? 2 : 3",
        "true ? 1 2 : false ? 3 : 4",
        "true ? 1e : false ? 3 : 4",
        "true ? 1e101 : false ? 3 : 4",
        'true ? "one" : false ? "two" : "${var.value}"',
        'true ? "one" : false ? "two" : "%{if true}three%{endif}"',
        r'true ? "one" : false ? "two" : "escaped\n"',
        'true ? "one" : false ? "two" : "three" # owned rationale',
        'true ? "one" : false /* owned rationale */ ? "two" : "three"',
        'true ? "one" : false ? "two" : "three" # sarj-noqa: SARJ215 -- contract',
        '(true ? "one" : false ? "two" : "three"',
        'true ? "one" : false ? "two" : "three" extra',
        'true ? "one" : false ? "two" : "\ud800"',
        "true ? " * 40 + "1" + " : 2" * 40,
    ],
)
def test_nonclosed_or_unowned_literal_selections_are_unchanged(expression: str) -> None:
    source = f"locals {{\n  value = {expression}\n}}\n"

    assert fix_source(Path("main.tf"), source, rule_ids=["no-nested-conditional"]) == source


@pytest.mark.parametrize(
    "source",
    [
        'locals { value = true ? "one" : false ? "two" : "three" }\n',
        'locals {\n  value = (\n    true ? "one" : false ? "two" : "three"\n  )\n}\n',
        'resource "example" "service" {\n  value = true ? "one" : false ? "two" : "three"\n}\n',
        'locals "invalid" {\n  value = true ? "one" : false ? "two" : "three"\n}\n',
        'locals {\n  value = true ? "one" : false ? "two" : "three" }\n',
        '# Generated by tool. Do not edit.\nlocals {\n  value = true ? "one" : false ? "two" : "three"\n}\n',
    ],
)
def test_ambiguous_or_nonlocal_literal_selection_targets_are_unchanged(source: str) -> None:
    assert fix_source(Path("main.tf"), source, rule_ids=["no-nested-conditional"]) == source


def test_literal_selection_respects_rule_selection_and_fixture_ownership() -> None:
    source = 'locals {\n  value = true ? "one" : false ? "two" : "three"\n}\n'

    assert fix_source(Path("main.tf"), source, rule_ids=[]) == source
    assert fix_source(Path("fixtures/main.tf"), source) == source
    assert fix_source(Path("main.tfvars"), source, rule_ids=["no-nested-conditional"]) == source


@pytest.mark.parametrize("condition", ["var.value != null", "null != (var.value)", "!(var.value == null)"])
@pytest.mark.parametrize("nullable", ["false", "true", "null", None])
@pytest.mark.parametrize("type_expression", ["string", "number", "bool"])
def test_nullability_validation_fixes_follow_upstream_diagnostic_authority(
    condition: str, nullable: str | None, type_expression: str
) -> None:
    nullability = "" if nullable is None else f"  nullable = {nullable}\n"
    validation = f'  validation {{\n    condition = {condition}\n    error_message = "Must not be null."\n  }}\n'
    source = f'variable "value" {{\n  type = {type_expression}\n{nullability}{validation}}}\n'
    path = Path("variables.tf")
    assert bool(NoRedundantVariableValidation().check(path, source)) is (nullable == "false")

    fixed = fix_source(path, source, rule_ids=["no-redundant-variable-validation"])

    assert fixed == (source.replace(validation, "\n\n\n\n") if nullable == "false" else source)
    assert fix_source(path, fixed, rule_ids=["no-redundant-variable-validation"]) == fixed


@pytest.mark.parametrize(
    "validation",
    [
        '  validation {\n    condition = var.value != null\n    error_message = "${var.message}"\n  }\n',
        '  validation {\n    # retain null contract rationale\n    condition = var.value != null\n    error_message = "Required."\n  }\n',
        '  validation {\n    condition = var.value != null && length(var.value) > 0\n    error_message = "Required."\n  }\n',
        '  validation {\n    condition = var.other != null\n    error_message = "Required."\n  }\n',
    ],
)
def test_nullability_fix_preserves_owned_or_distinct_validation(validation: str) -> None:
    source = f'variable "value" {{\n  type = string\n  nullable = false\n{validation}}}\n'

    assert fix_source(Path("variables.tf"), source, rule_ids=["no-redundant-variable-validation"]) == source


@pytest.fixture(scope="session")
def terraform_executable() -> str:
    executable = shutil.which("terraform")
    assert executable is not None, "Terraform 1.17.2 is required for the mandatory IaC semantic contract"
    version = subprocess.run((executable, "version"), check=True, capture_output=True, text=True)
    assert version.stdout.splitlines()[0] == "Terraform v1.17.2"
    return executable


def test_combined_project_fixes_preserve_provider_free_plans_and_instance_addresses(
    tmp_path: Path, terraform_executable: str
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    (child / "main.tf").write_text('resource "terraform_data" "child" { input = "retained" }\n')
    implementation = tmp_path / "service.tf"
    implementation.write_text(
        'variable "name" {\n  type = string\n  default = "retained"\n}\n'
        'resource "terraform_data" "kept" {\n  count = true ? 1 : 0 #\n  input = var.name\n}\n'
        'module "child" {\n  source = "./child"\n  count = false ? 0 : 1\n}\n'
        'output "names" { value = terraform_data.kept[*].output }\n'
    )
    (tmp_path / "variables.tf").write_text('variable "other" {\n  type = string\n  default = "owned"\n}\n')
    (tmp_path / "outputs.tf").write_text('output "other" { value = var.other }\n')
    _terraform_command(terraform_executable, tmp_path, "init", "-backend=false", "-input=false", "-no-color")
    before = _planned_values(terraform_executable, tmp_path)

    assert (
        main(
            [
                "check",
                "--rule",
                "conditional-resource-presence",
                "--rule",
                "no-terraform-comments",
                "--fix",
                str(implementation),
            ]
        )
        == 0
    )
    sources = {path: path.read_text() for path in tmp_path.glob("*.tf")}
    for path, source in consolidate_declarations(sources, selected=tuple(sources)).items():
        path.write_text(source)
    _terraform_command(terraform_executable, tmp_path, "fmt", "-recursive")

    assert _planned_values(terraform_executable, tmp_path) == before
    assert "count = 1" in implementation.read_text()
    assert 'variable "name"' in (tmp_path / "variables.tf").read_text()
    assert 'output "names"' in (tmp_path / "outputs.tf").read_text()
    fixed = {path: path.read_bytes() for path in sources}
    assert (
        main(
            [
                "check",
                "--rule",
                "conditional-resource-presence",
                "--rule",
                "no-terraform-comments",
                "--fix",
                str(implementation),
            ]
        )
        == 0
    )
    assert consolidate_declarations({path: path.read_text() for path in sources}, selected=tuple(sources)) == {}
    _terraform_command(terraform_executable, tmp_path, "fmt", "-check", "-recursive")
    assert {path: path.read_bytes() for path in sources} == fixed


def _terraform_command(executable: str, root: Path, *arguments: str) -> str:
    return subprocess.run(
        (executable, *arguments), cwd=root, check=True, capture_output=True, text=True, timeout=30
    ).stdout


def _planned_values(executable: str, root: Path) -> str:
    _terraform_command(executable, root, "plan", "-refresh=false", "-lock=false", "-input=false", "-out=proof.tfplan")
    plan = parse_json(_terraform_command(executable, root, "show", "-json", "proof.tfplan"))
    assert is_object_mapping(plan)
    return json.dumps(
        {"planned_values": plan["planned_values"], "resource_changes": plan["resource_changes"]}, sort_keys=True
    )


@pytest.mark.parametrize(("expression", "expected"), _CLOSED_CASES)
def test_closed_literal_fixes_preserve_real_terraform_value_and_type(
    tmp_path: Path, terraform_executable: str, expression: str, expected: str
) -> None:
    source = f"locals {{\n  value = {expression}\n}}\n"
    path = tmp_path / "main.tf"
    path.write_text(source, encoding="utf-8")
    before = _terraform_value(terraform_executable, tmp_path)
    fixed = fix_source(Path("main.tf"), source, rule_ids=["no-nested-conditional"])
    assert fixed == f"locals {{\n  value = {expected}\n}}\n"
    path.write_text(fixed, encoding="utf-8")

    assert _terraform_value(terraform_executable, tmp_path) == before


@pytest.mark.parametrize("condition", ["var.value != null", "null != (var.value)", "!(var.value == null)"])
def test_nonnull_validation_fixes_preserve_real_terraform_value_and_type(
    tmp_path: Path, terraform_executable: str, condition: str
) -> None:
    source = (
        'variable "value" {\n'
        '  type = string\n  nullable = false\n  default = "owned"\n'
        "  validation {\n"
        f"    condition = {condition}\n"
        '    error_message = "Must not be null."\n'
        "  }\n"
        "}\n"
        "locals {\n  value = var.value\n}\n"
    )
    path = tmp_path / "main.tf"
    path.write_text(source, encoding="utf-8")
    before = _terraform_value(terraform_executable, tmp_path)
    fixed = fix_source(Path("variables.tf"), source, rule_ids=["no-redundant-variable-validation"])
    assert fixed != source
    path.write_text(fixed, encoding="utf-8")

    assert _terraform_value(terraform_executable, tmp_path) == before


@dataclass(frozen=True, slots=True)
class _TerraformValue:
    rendered: str
    type_name: str


def _terraform_value(executable: str, root: Path) -> _TerraformValue:
    def evaluate(expression: str) -> str:
        completed = subprocess.run(
            (executable, "console", "-no-color"),
            cwd=root,
            input=expression + "\n",
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return completed.stdout.strip()

    return _TerraformValue(rendered=evaluate("local.value"), type_name=evaluate("type(local.value)"))


@pytest.mark.parametrize(
    ("scalar", "other"), [("1", "2"), ("true", "false"), ('"left"', '"right"')], ids=("number", "boolean", "string")
)
@pytest.mark.parametrize("condition", ["true", "false"])
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_complexity_and_empty_comment_profiles_preserve_real_terraform_value_and_type(
    tmp_path: Path, terraform_executable: str, *, scalar: str, other: str, condition: str, ending: str
) -> None:
    expression = scalar
    for _ in range(7):
        expression = f"{condition} ? ({expression}) : {other}"
    source = f"#\n/**/\nlocals {{\n  value = {expression}\n}}\n".replace("\n", ending)
    path = tmp_path / "main.tf"
    path.write_bytes(source.encode())
    before = _terraform_value(terraform_executable, tmp_path)

    fixed = fix_source(Path("main.tf"), source, rule_ids=["no-terraform-comments", "expression-complexity"])

    selected = scalar if condition == "true" else other
    assert fixed == f" \n    \nlocals {{\n  value = {selected}\n}}\n".replace("\n", ending)
    path.write_bytes(fixed.encode())
    assert _terraform_value(terraform_executable, tmp_path) == before
    assert fix_source(Path("main.tf"), fixed, rule_ids=["no-terraform-comments", "expression-complexity"]) == fixed
