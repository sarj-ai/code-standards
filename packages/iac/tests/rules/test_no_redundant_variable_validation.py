from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_iac_lint.rule_base import is_suppressed
from sarj_iac_lint.rules.no_redundant_variable_validation import NoRedundantVariableValidation


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_iac_lint.rule_base import RuleExample


_DOCUMENTATION = NoRedundantVariableValidation.documentation
assert _DOCUMENTATION is not None
_EXAMPLES = _DOCUMENTATION.examples


def _check(tmp_path: Path, source: str, *, relative: str = "variables.tf"):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    return NoRedundantVariableValidation().check(path, source)


@pytest.mark.parametrize("example", _EXAMPLES, ids=tuple(example.example_id for example in _EXAMPLES))
def test_documentation_examples_are_executable(example: RuleExample, tmp_path: Path) -> None:
    finding_count = 0
    for file in example.files:
        path = tmp_path / file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(file.source, encoding="utf-8")
        if file.path == example.focus_path:
            finding_count = len(NoRedundantVariableValidation().check(path, file.source))

    assert finding_count == example.expected_count


@pytest.mark.parametrize(
    ("type_expression", "condition"),
    [
        ("string", "can(tostring(var.name))"),
        ("number", "can(tonumber(var.replicas))"),
        ("bool", "can(tobool(var.enabled))"),
        ("list(string)", "can(tolist(var.names))"),
        ("set(string)", "can(toset(var.names))"),
        ("map(string)", "can(tomap(var.labels))"),
    ],
)
def test_flags_conversion_already_guaranteed_by_declared_type(
    tmp_path: Path,
    type_expression: str,
    condition: str,
) -> None:
    variable_name = condition.split("var.", 1)[1].split(")", 1)[0]
    source = (
        f'variable "{variable_name}" {{\n'
        f"  type = {type_expression}\n"
        "  validation {\n"
        f"    condition     = {condition}\n"
        '    error_message = "Must have the declared type."\n'
        "  }\n"
        "}\n"
    )

    diagnostics = _check(tmp_path, source)

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ209"
    assert diagnostics[0].line == 4


def test_flags_direct_can_of_declared_variable(tmp_path: Path) -> None:
    diagnostics = _check(
        tmp_path,
        'variable "name" {\n'
        "  type = string\n"
        "  validation {\n"
        "    condition = can(var.name)\n"
        '    error_message = "Must be readable."\n'
        "  }\n"
        "}\n",
    )

    assert len(diagnostics) == 1
    assert "declared `string` type" in diagnostics[0].message


@pytest.mark.parametrize(
    ("type_expression", "condition"),
    [
        ("string", "can(length(var.name))"),
        ("list(string)", "can(length(var.names))"),
        ("set(string)", "can(length(var.names))"),
        ("map(string)", "can(keys(var.labels))"),
        ("object({ team = string })", "can(keys(var.labels))"),
    ],
)
def test_flags_supported_operation_for_non_nullable_type(
    tmp_path: Path,
    type_expression: str,
    condition: str,
) -> None:
    variable_name = condition.split("var.", 1)[1].split(")", 1)[0]
    diagnostics = _check(
        tmp_path,
        f'variable "{variable_name}" {{\n'
        f"  type     = {type_expression}\n"
        "  nullable = false\n"
        "  validation {\n"
        f"    condition = ({condition})\n"
        '    error_message = "Must support this operation."\n'
        "  }\n"
        "}\n",
    )

    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    "condition",
    [
        "var.enabled == true || var.enabled == false",
        "false == var.enabled || true == var.enabled",
        "contains([true, false], var.enabled)",
        "contains([false, true], var.enabled)",
    ],
)
def test_flags_exhaustive_boolean_validation_when_null_is_forbidden(tmp_path: Path, condition: str) -> None:
    diagnostics = _check(
        tmp_path,
        'variable "enabled" {\n'
        "  type     = bool\n"
        "  nullable = false\n"
        "  validation {\n"
        f"    condition = {condition}\n"
        '    error_message = "Must be true or false."\n'
        "  }\n"
        "}\n",
    )

    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    ("type_expression", "condition"),
    [
        ("string", "can(tonumber(var.value))"),
        ("string", 'can(regex("^[a-z]+$", var.value))'),
        ("string", 'contains(["dev", "prod"], var.value)'),
        ("number", "var.value >= 1 && var.value <= 10"),
        ("list(string)", "length(var.value) > 0"),
        ("map(string)", 'contains(keys(var.value), "owner")'),
        ("object({ start = number, end = number })", "var.value.start < var.value.end"),
    ],
)
def test_preserves_domain_validations(tmp_path: Path, type_expression: str, condition: str) -> None:
    diagnostics = _check(
        tmp_path,
        'variable "value" {\n'
        f"  type = {type_expression}\n"
        "  validation {\n"
        f"    condition = {condition}\n"
        '    error_message = "Domain invariant."\n'
        "  }\n"
        "}\n",
    )

    assert diagnostics == []


@pytest.mark.parametrize(
    ("type_expression", "condition"),
    [
        ("string", "can(length(var.value))"),
        ("map(string)", "can(keys(var.value))"),
        ("bool", "var.value == true || var.value == false"),
        ("bool", "contains([true, false], var.value)"),
    ],
)
def test_preserves_null_guards_for_nullable_variables(
    tmp_path: Path,
    type_expression: str,
    condition: str,
) -> None:
    diagnostics = _check(
        tmp_path,
        'variable "value" {\n'
        f"  type = {type_expression}\n"
        "  validation {\n"
        f"    condition = {condition}\n"
        '    error_message = "Value must not be null."\n'
        "  }\n"
        "}\n",
    )

    assert diagnostics == []


def test_preserves_validation_of_a_different_variable(tmp_path: Path) -> None:
    diagnostics = _check(
        tmp_path,
        'variable "name" {\n'
        "  type = string\n"
        "  validation {\n"
        "    condition = can(tostring(var.other_name))\n"
        '    error_message = "Dependency must be convertible."\n'
        "  }\n"
        "}\n",
    )

    assert diagnostics == []


@pytest.mark.parametrize("type_expression", ["any", "tuple([string, number])"])
def test_preserves_dynamic_or_heterogeneous_conversions(tmp_path: Path, type_expression: str) -> None:
    diagnostics = _check(
        tmp_path,
        'variable "value" {\n'
        f"  type = {type_expression}\n"
        "  validation {\n"
        "    condition = can(tolist(var.value))\n"
        '    error_message = "Must convert to a homogeneous list."\n'
        "  }\n"
        "}\n",
    )

    assert diagnostics == []


def test_reports_each_redundant_validation_once(tmp_path: Path) -> None:
    diagnostics = _check(
        tmp_path,
        'variable "name" {\n'
        "  type = string\n"
        "  validation {\n"
        "    condition = can(var.name)\n"
        '    error_message = "Readable."\n'
        "  }\n"
        "  validation {\n"
        "    condition = can(tostring(var.name))\n"
        '    error_message = "String."\n'
        "  }\n"
        "}\n",
    )

    assert [(diagnostic.line, diagnostic.col) for diagnostic in diagnostics] == [(4, 5), (8, 5)]


def test_diagnostic_supports_exact_code_suppression(tmp_path: Path) -> None:
    source = (
        'variable "name" {\n'
        "  type = string\n"
        "  validation {\n"
        "    condition = can(tostring(var.name)) # sarj-noqa: SARJ209 — compatibility contract\n"
        '    error_message = "String."\n'
        "  }\n"
        "}\n"
    )
    diagnostics = _check(tmp_path, source)

    assert len(diagnostics) == 1
    assert is_suppressed(source.splitlines(), diagnostics[0].line, diagnostics[0].code)


@pytest.mark.parametrize("relative", ["fixtures/variables.tf", "testdata/variables.tf", "values.tfvars"])
def test_excludes_fixture_and_non_configuration_inputs(tmp_path: Path, relative: str) -> None:
    diagnostics = _check(
        tmp_path,
        'variable "name" {\n  type = string\n  validation { condition = can(tostring(var.name)) }\n}\n',
        relative=relative,
    )

    assert diagnostics == []


def test_excludes_generated_hcl(tmp_path: Path) -> None:
    diagnostics = _check(
        tmp_path,
        "# Generated by schema compiler; DO NOT EDIT.\n"
        'variable "name" {\n'
        "  type = string\n"
        "  validation { condition = can(tostring(var.name)) }\n"
        "}\n",
    )

    assert diagnostics == []


def test_ignores_comments_strings_and_malformed_hcl(tmp_path: Path) -> None:
    diagnostics = _check(
        tmp_path,
        '# variable "name" { type = string validation { condition = can(tostring(var.name)) } }\n'
        'locals { example = "can(tostring(var.name))" }\n'
        'variable "unfinished" {\n',
    )

    assert diagnostics == []


def test_ignores_malformed_type_constructor(tmp_path: Path) -> None:
    diagnostics = _check(
        tmp_path,
        'variable "names" {\n'
        "  type = list(string])\n"
        "  validation {\n"
        "    condition = can(tolist(var.names))\n"
        '    error_message = "List."\n'
        "  }\n"
        "}\n",
    )

    assert diagnostics == []
