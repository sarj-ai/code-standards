from __future__ import annotations

from pathlib import Path

import pytest

from sarj_iac_lint import _hcl  # sarj-noqa: SARJ048 -- Lexer spans expose otherwise-omitted heredoc data.
from sarj_iac_lint.autofix import fix_source
from sarj_iac_lint.rules import REGISTRY


_SEPARATORS = ["\u2028", "\x85", "\f", "\u2029"]


@pytest.mark.parametrize("separator", _SEPARATORS)
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
@pytest.mark.parametrize("kind", ["validation", "precondition"])
def test_real_assertion_fix_preserves_lexed_heredoc_value(separator: str, ending: str, kind: str) -> None:
    fake = separator.join(
        ("prefix", "a", "b", "c", "d", f"{kind} {{", "condition = true", 'error_message = "fake"', "}", "suffix")
    )
    prefix = ending.join(("locals {", "  banner = <<EOF", fake, "EOF", "}", ""))
    if kind == "validation":
        block = ending.join(
            (
                "  validation {",
                "    condition = can(tostring(var.x))",
                '    error_message = "Must be a string."',
                "  }",
                "",
            )
        )
        source = prefix + ending.join(('variable "x" {', "  type = string", "")) + block + "}" + ending
        rule_id = "no-redundant-variable-validation"
    else:
        block = ending.join(
            ("    precondition {", "      condition = true", '      error_message = "Always passes."', "    }", "")
        )
        source = (
            prefix
            + ending.join(('resource "terraform_data" "guard" {', "  lifecycle {", ""))
            + block
            + ending.join(("  }", "}", ""))
        )
        rule_id = "no-terraform-data-condition"
    native = REGISTRY[rule_id]()
    assert len(native.check(Path("main.tf"), source)) == 1

    fixed = fix_source(Path("main.tf"), source, rule_ids=[rule_id])

    assert fixed == source.replace(block, ending * 4)
    assert fixed.startswith(prefix)
    assert _heredoc_values(source) == _heredoc_values(fixed) == (fake + ending,)
    assert _hcl.document(fixed).blocks
    assert native.check(Path("main.tf"), fixed) == []
    assert fix_source(Path("main.tf"), fixed, rule_ids=[rule_id]) == fixed


def _heredoc_values(source: str) -> tuple[str, ...]:
    # The public token projection intentionally omits heredoc bodies; inspect the actual lexer spans to verify data preservation.
    lexical = _hcl._lexical_document(source)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- Actual lexer spans verify heredoc values omitted by the public token projection.
    assert lexical.complete
    return tuple(source[span.body_start : span.body_end] for span in lexical.values if span.kind == "heredoc")


@pytest.mark.parametrize("separator", _SEPARATORS)
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_comment_fix_still_removes_real_banner_outside_heredoc(separator: str, ending: str) -> None:
    body = separator.join(("prefix", "a", "b", "# ========", "suffix"))
    prefix = ending.join(("locals {", "  banner = <<EOF", body, "EOF", "}", ""))
    source = prefix + "# ========" + ending
    native = REGISTRY["no-comment-cruft"]()
    findings = native.check(Path("main.tf"), source)
    assert len(findings) == 1
    assert findings[0].line == 6

    fixed = fix_source(Path("main.tf"), source, rule_ids=["no-comment-cruft"])

    assert fixed == prefix + ending
    assert _heredoc_values(source) == _heredoc_values(fixed) == (body + ending,)
    assert native.check(Path("main.tf"), fixed) == []
    assert fix_source(Path("main.tf"), fixed, rule_ids=["no-comment-cruft"]) == fixed


@pytest.mark.parametrize("separator", _SEPARATORS)
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_nested_literal_fix_preserves_unicode_neighbor(separator: str, ending: str) -> None:
    source = ending.join(
        (
            "locals {",
            "  banner = <<EOF",
            f"before{separator}after",
            "EOF",
            '  value = true ? "left" : false ? "middle" : "right"',
            "}",
            "",
        )
    )
    rule_id = "no-nested-conditional"
    native = REGISTRY[rule_id]()
    assert len(native.check(Path("main.tf"), source)) == 1

    fixed = fix_source(Path("main.tf"), source, rule_ids=[rule_id])

    assert fixed == source.replace('true ? "left" : false ? "middle" : "right"', '"left"')
    assert _heredoc_values(source) == _heredoc_values(fixed)
    assert native.check(Path("main.tf"), fixed) == []
    assert fix_source(Path("main.tf"), fixed, rule_ids=[rule_id]) == fixed


@pytest.mark.parametrize("separator", [*_SEPARATORS, "\r"])
def test_hcl_physical_lines_do_not_treat_lone_cr_as_line_break(separator: str) -> None:
    source = f'locals {{ banner = "a{separator}b" }}\n'
    assert _hcl.physical_lines(source, keepends=True) == [source]
    assert _hcl.physical_lines(source) == [source.removesuffix("\n")]
