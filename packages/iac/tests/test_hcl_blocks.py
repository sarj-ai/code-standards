"""Tests for `_hcl.blocks()` lexical block-tree walker."""

from __future__ import annotations

import pytest

# `_hcl` is package-private by design; the walker is exercised directly because
# its guards (masking, nesting, value rejoining) are what the rules depend on.
from sarj_iac_lint._hcl import blocks, tokens


def test_tokens_keeps_an_interpolated_string_whole():
    """SARJ204 relies on this: an interpolated reference is never an operand token."""
    assert tokens('"cache-${var.environment}"') == ('"cache-${var.environment}"',)


def test_tokens_keeps_multichar_operators_whole():
    """SARJ204 reads comparisons by index, so `==` must not split into two tokens."""
    assert tokens('var.env=="prod"') == ("var.env", "==", '"prod"')
    assert tokens('var.env != "prod"') == ("var.env", "!=", '"prod"')


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
