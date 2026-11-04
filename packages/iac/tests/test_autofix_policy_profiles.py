from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts import RuleId

from sarj_iac_lint._hcl import comment_locations, tokens
from sarj_iac_lint.autofix import fix_source
from sarj_iac_lint.rules.expression_complexity import ExpressionComplexity
from sarj_iac_lint.rules.no_terraform_comments import NoTerraformComments


_COMMENTS = RuleId("no-terraform-comments")
_COMPLEXITY = RuleId("expression-complexity")


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("#\nlocals { value = 1 }\n", " \nlocals { value = 1 }\n", id="hash-line"),
        pytest.param("//\nlocals { value = 1 }\n", "  \nlocals { value = 1 }\n", id="slash-line"),
        pytest.param("  # \t\nlocals { value = 1 }\n", "     \nlocals { value = 1 }\n", id="indented-whitespace"),
        pytest.param("locals {\n  value = 1 #\n}\n", "locals {\n  value = 1  \n}\n", id="inline-line-comment"),
        pytest.param("locals {\n  value = 1/**/+2\n}\n", "locals {\n  value = 1    +2\n}\n", id="operator-boundary"),
        pytest.param("/**/\nlocals { value = 1 }\n", "    \nlocals { value = 1 }\n", id="block-before-declaration"),
        pytest.param("/* \t */\nlocals { value = 1 }\n", "       \nlocals { value = 1 }\n", id="block-whitespace"),
        pytest.param(
            'locals {\n  value = "λ\u2028data" //\t\n}\n',
            'locals {\n  value = "λ\u2028data"    \n}\n',
            id="unicode-column",
        ),
        pytest.param(
            'locals {\n  value = "${1 #\n  }"\n}\n#\n',
            'locals {\n  value = "${1 #\n  }"\n}\n \n',
            id="retained-template-comment",
        ),
        pytest.param(
            "# sarj-noqa: SARJ216 -- invalid self-suppression\n#\nlocals { value = 1 }\n",
            "# sarj-noqa: SARJ216 -- invalid self-suppression\n \nlocals { value = 1 }\n",
            id="nonsuppressible-rule",
        ),
        pytest.param("#", " ", id="hash-at-eof"),
        pytest.param("//", "  ", id="slash-at-eof"),
        pytest.param("/**/", "    ", id="block-at-eof"),
    ],
)
def test_empty_policy_comments_preserve_tokens_and_converge(source: str, expected: str, ending: str) -> None:
    source = source.replace("\n", ending)
    expected = expected.replace("\n", ending)

    fixed = fix_source(Path("main.tf"), source, rule_ids=[_COMMENTS])

    assert fixed == expected
    assert tokens(source) == tokens(fixed)
    assert fix_source(Path("main.tf"), fixed, rule_ids=[_COMMENTS]) == fixed


@pytest.mark.parametrize(
    "source",
    [
        "/*\n*/\nlocals { value = 1 }\n",
        "# Keep the security invariant.\nlocals { value = 1 }\n",
        "# tfsec:ignore:example\nlocals { value = 1 }\n",
        "# SPDX-License-Identifier: MIT\nlocals { value = 1 }\n",
        "# Code generated. DO NOT EDIT.\n#\nlocals { value = 1 }\n",
        'locals { value = "# // /**/" }\n',
        "locals { script = <<DOC\n#\n//\n/**/\nDOC\n}\n",
        '#\nlocals { value = "unterminated\n',
        "#\nlocals { value = (\n",
    ],
)
def test_policy_comment_fix_keeps_unproved_or_owned_source(source: str) -> None:
    assert fix_source(Path("main.tf"), source, rule_ids=[_COMMENTS]) == source


@pytest.mark.parametrize("path", ["main.tfvars", "config.hcl", "fixtures/main.tf", "generated/main.tf"])
def test_policy_comment_fixes_follow_native_ownership(path: str) -> None:
    source = "#\nlocals { value = 1 }\n"
    assert fix_source(Path(path), source, rule_ids=[_COMMENTS]) == source


def test_regular_comment_projection_preserves_default_template_analysis() -> None:
    source = '# ordinary\nlocals {\n  value = "${1 # template\n  }"\n}\n// ordinary\n'

    assert comment_locations(source) == ((1, 1), (3, 16), (6, 1))
    assert comment_locations(source, include_templates=False) == ((1, 1), (6, 1))
    assert len(NoTerraformComments().check(Path("main.tf"), source)) == 3


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_empty_comment_fixes_compose_with_existing_comment_profiles(ending: str) -> None:
    source = "# ==== Resources ====\n#\n\n# value = 2\n/**/\nlocals { value = 1 }\n".replace("\n", ending)

    fixed = fix_source(Path("main.tf"), source)

    assert tokens(source) == tokens(fixed)
    assert NoTerraformComments().check(Path("main.tf"), fixed) == []
    assert fix_source(Path("main.tf"), fixed) == fixed


@pytest.mark.parametrize(
    "leaf",
    ["var.value", 'file("missing")', "null", '"mixed"', "1e101", '"${var.value}"'],
)
def test_complexity_fix_retains_existing_scalar_guardrails(leaf: str) -> None:
    expression = leaf
    for _ in range(7):
        expression = f"true ? ({expression}) : 2"
    source = f"locals {{\n  value = {expression}\n}}\n"
    assert ExpressionComplexity().check(Path("main.tf"), source)

    assert fix_source(Path("main.tf"), source, rule_ids=[_COMPLEXITY]) == source


def test_complexity_fix_keeps_symbolic_predicates_and_real_validation() -> None:
    condition = " && ".join(f"var.value_{index} > 0" for index in range(7))
    source = f"locals {{\n  value = {condition}\n}}\n"
    assert ExpressionComplexity().check(Path("main.tf"), source)
    assert fix_source(Path("main.tf"), source, rule_ids=[_COMPLEXITY]) == source
    expression = "true ? (" * 7 + "1" + ") : 2" * 7
    validation = f'variable "value" {{\n  type = number\n  validation {{\n    condition = {expression}\n    error_message = "Invalid value."\n  }}\n}}\n'
    assert ExpressionComplexity().check(Path("main.tf"), validation)
    assert fix_source(Path("main.tf"), validation, rule_ids=[_COMPLEXITY]) == validation


def test_new_policy_profiles_respect_explicit_empty_selection() -> None:
    source = "#\nlocals { value = 1 }\n"
    assert fix_source(Path("main.tf"), source, rule_ids=[]) == source
