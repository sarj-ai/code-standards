from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_iac_lint.__main__ import analyze
from sarj_iac_lint.rules.expression_complexity import ExpressionComplexity


def test_documented_examples() -> None:
    verify_native_rule(ExpressionComplexity, analyze)


def _conjunction(count: int) -> str:
    return " && ".join(f"var.value_{index} > 0" for index in range(count))


def test_rejects_complex_statement_without_counting_physical_lines() -> None:
    expression = _conjunction(7)
    rule = ExpressionComplexity()

    findings = rule.check(Path("main.tf"), f"locals {{\n  ready = ({expression})\n}}\n")
    multiline = expression.replace(" && ", " &&\n    ")
    wrapped = rule.check(Path("main.tf"), f"locals {{\n  ready = (\n    {multiline}\n  )\n}}\n")

    assert len(findings) == len(wrapped) == 1
    assert findings[0].line == 2
    assert "13" in findings[0].message
    assert "12" in findings[0].message


def test_validation_has_a_tighter_budget_than_an_ordinary_statement() -> None:
    expression = _conjunction(4)
    source = (
        f'variable "value" {{\n  type = number\n  validation {{\n    condition = {expression}\n'
        '    error_message = "Supply a supported value."\n  }\n}\n'
        f"locals {{\n  ready = {expression}\n}}\n"
    )

    findings = ExpressionComplexity().check(Path("variables.tf"), source)

    assert len(findings) == 1
    assert findings[0].line == 4
    assert "validation" in findings[0].message.lower()
    assert "6" in findings[0].message


@pytest.mark.parametrize(
    "condition",
    [
        "var.port > 0 && var.port < 65536",
        'contains(["small", "large"], var.size)',
        "length(var.anchors) > 0",
        'can(regex("^[a-z]+$", var.name))',
        "alltrue([for anchor in var.anchors : length(anchor) > 0])",
        'alltrue([for value in var.values : value != null if(value != "")])',
    ],
)
def test_preserves_small_domain_validations(condition: str) -> None:
    source = f'variable "value" {{\n  type = string\n  validation {{\n    condition = {condition}\n    error_message = "Invalid input."\n  }}\n}}\n'

    assert ExpressionComplexity().check(Path("variables.tf"), source) == []


def test_counts_nested_comprehensions_and_function_calls() -> None:
    expression = "alltrue([for group in var.groups : alltrue([for item in group : can(regex(var.pattern, trimspace(lower(item)))) && length(item) > 0])])"
    source = f'variable "groups" {{\n  type = list(list(string))\n  validation {{\n    condition = {expression}\n    error_message = "Invalid entries."\n  }}\n}}\n'

    assert len(ExpressionComplexity().check(Path("main.tf"), source)) == 1


@pytest.mark.parametrize("validation", [False, True])
def test_accepts_the_exact_complexity_budget(*, validation: bool) -> None:
    expression = "!(" + _conjunction(3 if validation else 6) + ")"
    source = (
        f'variable "value" {{\n  type = number\n  validation {{\n    condition = {expression}\n    error_message = "Invalid input."\n  }}\n}}\n'
        if validation
        else f"locals {{\n  ready = {expression}\n}}\n"
    )

    assert ExpressionComplexity().check(Path("main.tf"), source) == []


def test_literal_data_comments_and_type_schemas_do_not_consume_the_budget() -> None:
    source = 'locals {\n  text = "for ? && contains(a) || for ? && contains(b)"\n  script = <<DOC\nfor ? && contains(a) || for ? && contains(b)\nDOC\n}\n'
    source += "# " + _conjunction(20) + "\n"
    source += (
        'variable "settings" { type = object({ ' + ", ".join(f"key_{i} = list(string)" for i in range(30)) + " }) }\n"
    )

    assert ExpressionComplexity().check(Path("main.tf"), source) == []


def test_counts_expressions_embedded_in_strings_and_heredocs() -> None:
    expression = _conjunction(7)
    source = f'locals {{\n  text = "${{{expression}}}"\n  rendered = <<DOC\n${{{expression}}}\nDOC\n}}\n'

    assert len(ExpressionComplexity().check(Path("main.tf"), source)) == 2


@pytest.mark.parametrize("interpolated", [False, True])
def test_preserves_heredoc_delimiters_inside_object_values(*, interpolated: bool) -> None:
    expression = _conjunction(7)
    body = "${" + expression + "}" if interpolated else expression
    source = "locals {\n  settings = {\n    script = <<DOC\n" + body + "\nDOC\n    enabled = true\n  }\n}\n"

    assert len(ExpressionComplexity().check(Path("main.tf"), source)) == (1 if interpolated else 0)


def test_does_not_cap_the_number_of_variables() -> None:
    source = "\n".join(f'variable "value_{i}" {{ type = string }}' for i in range(30))

    assert ExpressionComplexity().check(Path("variables.tf"), source) == []


def test_malformed_input_is_left_to_the_native_parser() -> None:
    assert ExpressionComplexity().check(Path("main.tf"), "locals { ready = (") == []
