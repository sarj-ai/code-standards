from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

# `_hcl` is package-private by design; the walker is exercised directly because
# its guards (masking, nesting, value rejoining) are what the rules depend on.
from sarj_iac_lint.__main__ import analyze
from sarj_iac_lint._hcl import (
    blocks,
    document,
    literal_string,
    literal_token,
    strip_outer_parentheses,
    suppression_comment_lines,
    tokens,
)
from sarj_iac_lint.rules import REGISTRY


if TYPE_CHECKING:
    from pathlib import Path


def test_tokens_keeps_an_interpolated_string_whole():
    assert tokens('"cache-${var.environment}"') == ('"cache-${var.environment}"',)


def test_tokens_keeps_multichar_operators_whole():
    assert tokens('var.env=="prod"') == ("var.env", "==", '"prod"')
    assert tokens('var.env != "prod"') == ("var.env", "!=", '"prod"')


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("((var.value))", "var.value"),
        ('("literal (value)")', '"literal (value)"'),
        ("(var.left) == (var.right)", "(var.left) == (var.right)"),
        ("((var.value)", "((var.value)"),
        ("(var.value))", "(var.value))"),
        ("((var.value) == (1))", "(var.value) == (1)"),
    ],
)
def test_parentheses_are_removed_only_when_they_enclose_the_whole_expression(source: str, expected: str) -> None:
    assert strip_outer_parentheses(tokens(source)) == tokens(expected)


def test_parses_type_labels_and_position():
    src = '\nresource "google_sql_database_instance" "main" {\n  name = "prod"\n}\n'
    (block,) = blocks(src)
    assert block.type == "resource"
    assert block.labels == ("google_sql_database_instance", "main")
    assert block.depth == 0
    assert block.line == 2
    assert block.col == 1
    assert block.end_line == 4


def test_nested_block_is_a_child_not_a_sibling_attribute():
    src = """
resource "google_sql_database_instance" "main" {
  name = "prod"
  settings {
    tier                        = "db-f1-micro"
    deletion_protection_enabled = true
  }
}
"""
    (block,) = blocks(src)
    # The whole bug SARJ201 had: the nested flag must NOT read as the resource's.
    assert block.attribute("deletion_protection_enabled") is None
    assert [a.name for a in block.attributes] == ["name"]
    (settings,) = block.blocks
    assert settings.type == "settings"
    assert settings.depth == 1
    assert settings.attribute("deletion_protection_enabled") is not None


def test_child_lookup_is_direct_only():
    src = """
resource "aws_db_instance" "x" {
  restore_to_point_in_time {
    lifecycle {
      prevent_destroy = true
    }
  }
}
"""
    (block,) = blocks(src)
    assert block.child("lifecycle") is None
    assert block.child("restore_to_point_in_time") is not None


def test_attribute_records_its_own_line_and_col():
    src = 'resource "aws_db_instance" "x" {\n  engine = "postgres"\n}\n'
    (block,) = blocks(src)
    attr = block.attribute("engine")
    assert attr is not None
    assert (attr.line, attr.col) == (2, 3)


def test_rejoins_a_value_split_across_lines():
    src = """
resource "aws_db_instance" "x" {
  deletion_protection = (
    var.env == "prod"
  )
}
"""
    (block,) = blocks(src)
    attr = block.attribute("deletion_protection")
    assert attr is not None
    assert attr.value == '( var.env == "prod" )'
    assert attr.line == 3  # the `deletion_protection` line, not the value's


def test_rejoins_a_bracketed_list_value():
    src = 'resource "aws_db_instance" "x" {\n  subnets = [\n    "a",\n    "b",\n  ]\n}\n'
    (block,) = blocks(src)
    attr = block.attribute("subnets")
    assert attr is not None
    assert attr.value == '[ "a", "b", ]'


def test_object_valued_attribute_is_not_a_block():
    src = 'resource "aws_db_instance" "x" {\n  tags = {\n    Name = "x"\n  }\n}\n'
    (block,) = blocks(src)
    assert block.blocks == ()
    assert block.attribute("tags") is not None


def test_single_line_block_body():
    src = 'resource "google_secret_manager_secret" "s" {\n  replication { auto {} }\n}\n'
    (block,) = blocks(src)
    (replication,) = block.blocks
    assert replication.type == "replication"
    assert [b.type for b in replication.blocks] == ["auto"]


def test_brace_inside_a_string_does_not_close_the_block():
    src = """
resource "google_sql_database_instance" "main" {
  description         = "closes with }"
  deletion_protection = true
}
"""
    (block,) = blocks(src)
    assert block.attribute("deletion_protection") is not None
    assert block.end_line == 5


def test_brace_inside_a_string_interpolation_does_not_close_the_block():
    src = """
resource "google_sql_database_instance" "main" {
  name                = "db-${lookup(local.m, "k")}-x"
  deletion_protection = true
}
"""
    (block,) = blocks(src)
    assert block.attribute("deletion_protection") is not None


def test_adversarial_interpolation_string_tokenizes_without_backtracking():
    hostile = "${{}}" * 10_000
    src = f'resource "example" "main" {{\n  value = "{hostile}"\n}}\n'
    (block,) = blocks(src)
    assert block.attribute("value") is not None


def test_commented_out_attribute_is_not_parsed():
    src = """
resource "google_sql_database_instance" "main" {
  # deletion_protection = true
  name = "prod"
}
"""
    (block,) = blocks(src)
    assert block.attribute("deletion_protection") is None


def test_heredoc_body_is_not_parsed_as_hcl():
    src = """
resource "google_sql_database_instance" "main" {
  startup = <<-EOT
    deletion_protection = true
    if true; then echo "}"; fi
  EOT
  name = "prod"
}
"""
    (block,) = blocks(src)
    assert block.attribute("deletion_protection") is None
    assert block.attribute("name") is not None
    assert block.end_line == 8


def test_multiple_top_level_blocks_and_non_resource_types():
    src = """
terraform {
  required_version = ">= 1.9"
}

removed {
  from = kubernetes_manifest.logto_service
}

resource "aws_db_instance" "a" {
  engine = "postgres"
}
"""
    assert [b.type for b in blocks(src)] == ["terraform", "removed", "resource"]


def test_document_exposes_file_level_attributes_and_owns_the_block_tree():
    src = 'top_level = "x"\n\ninclude "root" {\n  path = "../root.hcl"\n}\n'
    root = document(src)
    assert not root.type
    assert root.labels == ()
    attr = root.attribute("top_level")
    assert attr is not None
    assert (attr.line, attr.col) == (1, 1)
    assert root.blocks == blocks(src)
    assert [b.type for b in root.blocks] == ["include"]


def test_document_of_an_empty_source_is_an_empty_root():
    root = document("")
    assert root.attributes == ()
    assert root.blocks == ()


def test_empty_and_unbalanced_sources_degrade_without_raising():
    assert blocks("") == ()
    assert blocks("# just a comment\n") == ()
    # Truncated file: parsed leniently rather than raising.
    (block,) = blocks('resource "aws_db_instance" "x" {\n  engine = "postgres"\n')
    assert block.labels == ("aws_db_instance", "x")


def test_excessive_nesting_fails_with_a_controlled_parse_error() -> None:
    source = "block {\n" * 200 + "}\n" * 200

    with pytest.raises(ValueError, match="nesting exceeds"):
        blocks(source)


@pytest.mark.parametrize("label", [r'"\u0061ws_db_instance"', r'"\U00000061ws_db_instance"'])
def test_escaped_block_labels_preserve_resource_identity(label: str) -> None:
    (block,) = blocks(f'resource {label} "main" {{\n  engine = "postgres"\n}}\n')
    assert block.labels == ("aws_db_instance", "main")
    assert (block.line, block.col) == (1, 1)


@pytest.mark.parametrize("value", [r'"\u0050REVENT"', r'"\U00000050REVENT"', '( ( "PREVENT" ) )'])
def test_literal_string_decodes_only_a_single_static_value(value: str) -> None:
    assert literal_string(value) == "PREVENT"


@pytest.mark.parametrize(
    "value",
    [
        '"${var.policy}"',
        '"%{ if true }PREVENT%{ endif }"',
        r'"\bPREVENT"',
        r'"\uD800"',
        r'"\uD83D\uDE00"',
        r'"\U00110000"',
        '"PREVENT" + "other"',
        '(("PREVENT")',
        '("PREVENT"))',
    ],
)
def test_unresolved_or_invalid_strings_do_not_prove_protection(value: str) -> None:
    assert literal_string(value) is None


@pytest.mark.parametrize(
    ("value", "expected"), [("((true))", "true"), ("(false)", "false"), ("(true) && (false)", None), ("t rue", None)]
)
def test_literal_token_requires_a_complete_single_token(value: str, expected: str | None) -> None:
    assert literal_token(value) == expected


def test_deep_parentheses_and_sibling_groups_preserve_expression_boundaries() -> None:
    assert strip_outer_parentheses(tokens("(" * 3000 + "true" + ")" * 3000)) == ("true",)
    assert strip_outer_parentheses(tokens("((left)(right))")) == tokens("(left)(right)")


def test_escaped_backslash_does_not_start_a_unicode_escape() -> None:
    assert literal_string(r'"\\U00000050REVENT"') == r"\U00000050REVENT"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('"$${var.fixture}"', "${var.fixture}"),
        ('"%%{if true}"', "%{if true}"),
        (r'"\u0024\u0024{"', "$${"),
        (r'"\u0024$${"', "$${"),
        ('"$${literal}${var.dynamic}"', None),
        ('"%%{literal}%{if true}dynamic%{endif}"', None),
    ],
)
def test_static_template_escapes_keep_lexical_decoding_order(source: str, expected: str | None) -> None:
    assert literal_string(source) == expected


_NATIVE_TEMPLATE_CASES = (
    (
        "literal-comment-data",
        'resource "google_service_account_key" "public" { keepers = { reason = "# sarj-noqa: SARJ211 -- source data" } }\n',
        1,
    ),
    (
        "nested-upper-data",
        'resource "google_service_account_key" "public" { keepers = { reason = "${upper("# sarj-noqa: SARJ211")}" } }\n',
        1,
    ),
    (
        "nested-lookup-data",
        'resource "google_service_account_key" "public" { keepers = { reason = "${lookup({tag = "# sarj-noqa: SARJ211"}, "tag", "default")}" } }\n',
        1,
    ),
    (
        "nested-object-data",
        'resource "google_service_account_key" "public" { keepers = { reason = "${jsonencode({one = {two = "# sarj-noqa: SARJ211"}})}" } }\n',
        1,
    ),
    (
        "nested-template-data",
        'resource "google_service_account_key" "public" { keepers = { reason = "${format("%s", "${upper("# sarj-noqa: SARJ211")}")}" } }\n',
        1,
    ),
    (
        "escaped-interpolation-data",
        'resource "google_service_account_key" "public" { keepers = { reason = "$${# sarj-noqa: SARJ211}" } }\n',
        1,
    ),
    (
        "escaped-directive-data",
        'resource "google_service_account_key" "public" { keepers = { reason = "%%{# sarj-noqa: SARJ211}" } }\n',
        1,
    ),
    (
        "nested-template-block-comment",
        'resource "google_service_account_key" "public" { keepers = { reason = "${upper(/* # sarj-noqa: SARJ211 */ "data")}" } }\n',
        1,
    ),
    (
        "nested-template-line-comment",
        'resource "google_service_account_key" "public" { keepers = { reason = "${upper( # sarj-noqa: SARJ211 -- expression comment\n "data")}" } }\n',
        1,
    ),
    (
        "nested-template-multiline-object",
        'resource "google_service_account_key" "public" { keepers = { reason = "${jsonencode({\n reason = "# sarj-noqa: SARJ211"\n})}" } }\n',
        1,
    ),
    (
        "template-control-data",
        'resource "google_service_account_key" "public" { keepers = { reason = "%{if upper("# sarj-noqa: SARJ211") != ""}data%{endif}" } }\n',
        1,
    ),
    (
        "nested-heredoc-in-template",
        'resource "google_service_account_key" "public" { keepers = { reason = "${<<EOT\n# sarj-noqa: SARJ211\nEOT\n}" } }\n',
        1,
    ),
    (
        "heredoc-value-data",
        'resource "google_service_account_key" "public" {\n reason = <<EOT\n# sarj-noqa: SARJ211\nEOT\n}\n',
        1,
    ),
    (
        "heredoc-template-nested-quote",
        'locals {\n reason = <<EOT\n${upper("# sarj-noqa: SARJ211")}\nEOT\n}\nresource "google_service_account_key" "public" {}\n',
        1,
    ),
    ("unicode-unrelated-code", 'locals { café = 1 }\nresource "google_service_account_key" "public" {}\n', 1),
    (
        "unicode-unrelated-true-waiver",
        'locals { café = 1 }\nresource "google_service_account_key" "public" {} # sarj-noqa: SARJ211 -- approved\n',
        1,
    ),
    ("inline-header-comments", 'resource /* type */ "google_service_account_key" /* name */ "public" {}\n', 1),
    ("multiline-header-comment", 'resource /* comment\n detail */ "google_service_account_key" "public" {}\n', 1),
    ("multiline-label-comment", 'resource "google_service_account_key" /* comment\n detail */ "public" {}\n', 1),
    (
        "multiline-header-comment-first-line-waiver",
        'resource /* # sarj-noqa: SARJ211 -- approved\n detail */ "google_service_account_key" "public" {}\n',
        1,
    ),
    ("structural-header-newline", 'resource\n "google_service_account_key" "public" {}\n', 0),
    ("structural-brace-newline", 'resource "google_service_account_key" "public"\n {}\n', 0),
    ("line-comment-header-break", 'resource # comment\n "google_service_account_key" "public" {}\n', 0),
    ("comment-then-header-break", 'resource /* comment\n detail */\n "google_service_account_key" "public" {}\n', 0),
    (
        "header-two-multiline-comments",
        'resource /* one\n two */ "google_service_account_key" /* three\n four */ "public" {}\n',
        1,
    ),
    ("real-line-waiver", 'resource "google_service_account_key" "public" {} # sarj-noqa: SARJ211 -- approved\n', 1),
    ("real-slash-waiver", 'resource "google_service_account_key" "public" {} // # sarj-noqa: SARJ211 -- approved\n', 1),
    (
        "real-block-waiver",
        'resource "google_service_account_key" "public" {} /* # sarj-noqa: SARJ211 -- approved */\n',
        1,
    ),
    (
        "template-with-real-waiver",
        'resource "google_service_account_key" "public" { keepers = { reason = "${jsonencode({reason = "# source data"})}" } } # sarj-noqa: SARJ211 -- approved\n',
        1,
    ),
    (
        "wrong-code-real-comment",
        'resource "google_service_account_key" "public" {} # sarj-noqa: SARJ201 -- other policy\n',
        1,
    ),
    (
        "literal-data-wrong-code-real-comment",
        'resource "google_service_account_key" "public" { keepers = { reason = "# sarj-noqa: SARJ211" } } # sarj-noqa: SARJ201 -- other policy\n',
        1,
    ),
    (
        "template-data-wrong-code-real-comment",
        'resource "google_service_account_key" "public" { keepers = { reason = "${upper("# sarj-noqa: SARJ211")}" } } # sarj-noqa: SARJ201 -- other policy\n',
        1,
    ),
    ("unclosed-block-comment", 'resource "google_service_account_key" "public" {} /* # sarj-noqa: SARJ211\n', 0),
    (
        "unclosed-template",
        'resource "google_service_account_key" "public" { keepers = { reason = "${upper("source")" } }\n',
        0,
    ),
    ("unclosed-string", 'resource "google_service_account_key" "public" { reason = "data\n', 0),
    ("unclosed-heredoc", 'resource "google_service_account_key" "public" {\n reason = <<EOT\n# source\n', 0),
)


@pytest.mark.parametrize(
    ("name", "source", "expected"), _NATIVE_TEMPLATE_CASES, ids=tuple(case[0] for case in _NATIVE_TEMPLATE_CASES)
)
@pytest.mark.parametrize("crlf", [False, True])
def test_shared_template_spans_preserve_native_resource_ownership(
    name: str, source: str, expected: int, crlf: bool, tmp_path: Path
) -> None:

    source = source.replace("\n", "\r\n") if crlf else source
    path = tmp_path / "main.tf"
    path.write_bytes(source.encode())
    rule = REGISTRY["no-managed-service-account-key"]()
    findings = rule.check(path, source)
    assert len(findings) == expected, name
    assert findings == rule.check(path, source)
    assert len({(item.code, item.line, item.col) for item in findings}) == len(findings)
    analyze(sorted(REGISTRY), [path])


def test_multiline_template_remains_one_token_with_exact_source() -> None:
    value = '"${jsonencode({\n reason = "# source data"\n})}"'
    assert tokens(value) == (value,)
    assert literal_string(value) is None


def test_shared_comment_index_reuses_one_immutable_projection() -> None:

    source = 'locals { value = "${upper("# source data")}" } # sarj-noqa: SARJ211 -- approved\n'
    comments = suppression_comment_lines(source)
    assert dict(comments) == {1: "# sarj-noqa: SARJ211 -- approved"}
    assert suppression_comment_lines(source) is comments


def test_malformed_file_does_not_break_multi_file_declaration_inference(tmp_path: Path) -> None:

    (tmp_path / "variables.tf").write_text('variable "region" { type = string }\n')
    (tmp_path / "malformed.tf").write_text('locals { value = "unterminated\n')
    path = tmp_path / "env" / "dev" / "terraform.tfvars"
    path.parent.mkdir(parents=True)
    path.write_text('region = "fixture"\n')
    assert analyze(["no-dead-environment-input"], [path]) == []


_NATIVE_VALUE_BOUNDARY_CASES = (
    (
        "protection-dynamic-after-comment",
        'resource "google_sql_database_instance" "public" {\n deletion_protection = true /* comment\n detail */ && false\n}\n',
        "require-deletion-protection",
        1,
    ),
    (
        "protection-static-comment",
        'resource "google_sql_database_instance" "public" {\n deletion_protection = true /* comment\n detail */\n}\n',
        "require-deletion-protection",
        0,
    ),
    (
        "protection-grouped-static-comment",
        'resource "google_sql_database_instance" "public" {\n deletion_protection = (true /* comment\n detail */)\n}\n',
        "require-deletion-protection",
        0,
    ),
    (
        "protection-next-attribute",
        'resource "google_sql_database_instance" "public" {\n deletion_protection = true\n name = "fixture"\n}\n',
        "require-deletion-protection",
        0,
    ),
    (
        "protection-false-next-attribute",
        'resource "google_sql_database_instance" "public" {\n deletion_protection = false\n name = "fixture"\n}\n',
        "require-deletion-protection",
        1,
    ),
    (
        "environment-comparison-after-comment",
        'resource "null_resource" "public" {\n count = var.environment /* comment\n detail */ == "prod" ? 1 : 0\n}\n',
        "no-environment-conditional",
        1,
    ),
    (
        "environment-comparison-normal-newline",
        'resource "null_resource" "public" {\n count = var.environment\n reason = "prod"\n}\n',
        "no-environment-conditional",
        0,
    ),
    (
        "conversion-after-comment",
        'variable "region" {\n type = string\n validation {\n condition = can /* comment\n detail */ (tostring(var.region))\n error_message = "Must be a string."\n }\n}\n',
        "no-redundant-variable-validation",
        1,
    ),
    (
        "line-comment-block-delimiter",
        '# explanatory /* source data\nresource "google_service_account_key" "public" {}\n',
        "no-managed-service-account-key",
        1,
    ),
    (
        "slash-comment-block-delimiter",
        '// explanatory /* source data\nresource "google_service_account_key" "public" {}\n',
        "no-managed-service-account-key",
        1,
    ),
    (
        "line-comment-quote",
        '# explanatory " source data\nresource "google_service_account_key" "public" {}\n',
        "no-managed-service-account-key",
        1,
    ),
)


@pytest.mark.parametrize(
    ("name", "source", "rule_id", "expected"),
    _NATIVE_VALUE_BOUNDARY_CASES,
    ids=tuple(case[0] for case in _NATIVE_VALUE_BOUNDARY_CASES),
)
@pytest.mark.parametrize("crlf", [False, True])
def test_comment_newlines_preserve_complete_value_ownership(
    name: str, source: str, rule_id: str, expected: int, tmp_path: Path, *, crlf: bool
) -> None:
    source = source.replace("\n", "\r\n") if crlf else source
    path = tmp_path / "main.tf"
    path.write_bytes(source.encode())
    findings = analyze([rule_id], [path])
    assert len(findings) == expected, name
    assert findings == analyze([rule_id], [path])
    analyze(sorted(REGISTRY), [path])


def test_comment_projection_tracks_source_changes_and_bounds_its_cache() -> None:
    initial = 'resource "google_service_account_key" "public" {} # sarj-noqa: SARJ211 -- approved\n'
    revised = 'resource "google_service_account_key" "public" { keepers = { reason = "# sarj-noqa: SARJ211" } }\n'
    assert suppression_comment_lines(initial).get(1)
    assert not suppression_comment_lines(revised)
    assert suppression_comment_lines(initial).get(1)
    for index in range(40):
        suppression_comment_lines(f'locals {{ value = "fixture-{index}" }} # ordinary\n')
    info = suppression_comment_lines.cache_info()
    assert info.maxsize is not None
    assert info.currsize <= info.maxsize
