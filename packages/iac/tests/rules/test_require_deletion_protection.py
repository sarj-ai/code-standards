from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_iac_lint.rules.require_deletion_protection import PROTECTED_TYPES, RequireDeletionProtection


if TYPE_CHECKING:
    from sarj_iac_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = RequireDeletionProtection.public_examples()


def _check(source: str, name: str = "main.tf") -> list[Diagnostic]:
    return RequireDeletionProtection().check(Path(name), source)


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = RequireDeletionProtection().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


def test_flags_missing_deletion_protection():
    src = """
resource "google_sql_database_instance" "main" {
  name = "prod"
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "no deletion_protection" in diags[0].message


def test_google_sql_database_requires_a_deletion_guard():
    src = """
resource "google_sql_database" "app" {
  name     = "app"
  instance = google_sql_database_instance.main.name
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "google_sql_database" in diags[0].message


def test_google_sql_database_accepts_exact_prevent_policy():
    src = """
resource "google_sql_database" "app" {
  name            = "app"
  instance        = google_sql_database_instance.main.name
  deletion_policy = "PREVENT"
}
"""
    assert _check(src) == []


def test_google_sql_database_accepts_lifecycle_prevent_destroy():
    src = """
resource "google_sql_database" "app" {
  name     = "app"
  instance = google_sql_database_instance.main.name
  lifecycle {
    prevent_destroy = true
  }
}
"""
    assert _check(src) == []


@pytest.mark.parametrize("value", ['"DELETE"', '"ABANDON"', '"prevent"', "PREVENT", "var.policy"])
def test_google_sql_database_rejects_unproven_deletion_policy(value: str):
    src = f"""resource "google_sql_database" "app" {{
  name            = "app"
  instance        = google_sql_database_instance.main.name
  deletion_policy = {value}
}}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "deletion_policy" in diags[0].message


def test_google_sql_database_does_not_accept_an_unsupported_boolean_guard():
    src = """
resource "google_sql_database" "app" {
  name                = "app"
  instance            = google_sql_database_instance.main.name
  deletion_protection = true
}
"""
    assert len(_check(src)) == 1


def test_flags_variable_gated_protection_as_unverifiable():
    src = """
resource "google_sql_database_instance" "logto" {
  deletion_protection = var.gke_deletion_protection
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "not a literal true" in diags[0].message


def test_allows_prevent_destroy_lifecycle():
    src = """
resource "google_container_cluster" "data" {
  name = "data"
  lifecycle {
    prevent_destroy = true
  }
}
"""
    assert _check(src) == []


def test_redis_is_protected_when_deletion_protection_is_omitted():
    src = """
resource "google_redis_instance" "cache" {
  name           = "session-cache"
  memory_size_gb = 4
}
"""
    assert _check(src) == []


def test_redis_explicit_false_is_unprotected():
    src = """
resource "google_redis_instance" "cache" {
  name                = "session-cache"
  deletion_protection = false
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "deletion_protection = false" in diags[0].message


@pytest.mark.parametrize("resource_type", ["google_redis_instance", "google_filestore_instance"])
def test_provider_deletion_policy_prevent_is_protection(resource_type: str):
    protection = "deletion_protection = false" if resource_type == "google_redis_instance" else ""
    src = f"""resource "{resource_type}" "main" {{
  name = "prod"
  {protection}
  deletion_policy = "PREVENT"
}}
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "resource_type",
    [
        "google_bigquery_dataset",
        "google_bigquery_table",
        "google_bigtable_instance",
        "google_container_cluster",
        "google_filestore_instance",
        "google_redis_instance",
        "google_spanner_database",
        "google_sql_database_instance",
    ],
)
def test_current_google_provider_deletion_policy_prevent_is_protection(resource_type: str):
    src = f"""resource "{resource_type}" "main" {{
  name                = "prod"
  deletion_protection = false
  deletion_policy     = "PREVENT"
}}
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "value",
    ['"DELETE"', '"ABANDON"', '"prevent"', '"PrEvEnT"', "PREVENT", "var.deletion_policy", "null"],
)
def test_google_deletion_policy_must_be_literal_prevent(value: str):
    src = f"""resource "google_sql_database_instance" "main" {{
  name            = "prod"
  deletion_policy = {value}
}}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "deletion_policy" in diags[0].message


def test_alloydb_force_deletion_policy_is_not_mistaken_for_protection():
    src = """resource "google_alloydb_cluster" "main" {
  cluster_id      = "prod"
  deletion_policy = "FORCE"
}
"""
    assert len(_check(src)) == 1


def test_filestore_requires_a_deletion_guard():
    src = """
resource "google_filestore_instance" "files" {
  name = "prod-files"
}
"""
    assert len(_check(src)) == 1


def test_filestore_deletion_protection_enabled_is_accepted():
    src = """
resource "google_filestore_instance" "files" {
  name                        = "prod-files"
  deletion_protection_enabled = true
}
"""
    assert _check(src) == []


def test_dynamodb_deletion_protection_enabled_is_accepted():
    src = """
resource "aws_dynamodb_table" "data" {
  deletion_protection_enabled = true
}
"""
    assert _check(src) == []


@pytest.mark.parametrize("value", ["false", "var.guard"])
def test_literal_prevent_destroy_overrides_an_unproven_provider_guard(value: str):
    src = f"""resource "google_container_cluster" "data" {{
  deletion_protection = {value}
  lifecycle {{
    prevent_destroy = true
  }}
}}"""
    assert _check(src) == []


def test_flags_explicitly_disabled():
    src = """
resource "google_container_cluster" "primary" {
  deletion_protection = false
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "false" in diags[0].message


def test_allows_protection_enabled():
    src = """
resource "google_sql_database_instance" "main" {
  name                = "prod"
  deletion_protection = true
}
"""
    assert _check(src) == []


def test_ignores_unprotected_resource_types():
    src = """
resource "google_storage_bucket_object" "x" {
  name = "y"
}
"""
    assert _check(src) == []


def test_handles_nested_blocks():
    src = """
resource "google_container_cluster" "primary" {
  node_config {
    machine_type = "e2-medium"
  }
  deletion_protection = true
}
"""
    assert _check(src) == []


def test_flags_each_unprotected_instance():
    src = """
resource "aws_db_instance" "a" {
  engine = "postgres"
}
resource "aws_db_instance" "b" {
  deletion_protection = true
}
"""
    assert len(_check(src)) == 1


def test_ignores_non_tf_files():
    src = 'resource "google_sql_database_instance" "main" {\n}\n'
    assert _check(src, name="notes.txt") == []


def test_brace_in_string_does_not_truncate_block():
    # A `}` inside a string must not end the block early and produce a phantom
    # "no deletion_protection" FP — the protected value comes after it.
    src = """
resource "google_sql_database_instance" "main" {
  description         = "closes with }"
  deletion_protection = true
}
"""
    assert _check(src) == []


def test_quoted_false_is_disabled():
    src = """
resource "google_sql_database_instance" "main" {
  deletion_protection = "false"
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "false" in diags[0].message


def test_quoted_true_is_protected():
    src = """
resource "google_sql_database_instance" "main" {
  deletion_protection = "true"
}
"""
    assert _check(src) == []


def test_heredoc_brace_does_not_truncate_block():
    src = """
resource "google_sql_database_instance" "main" {
  user_labels = jsonencode({})
  startup     = <<-EOT
    if true; then echo "}"; fi
  EOT
  deletion_protection = true
}
"""
    assert _check(src) == []


def test_flags_newly_allowlisted_dynamodb():
    src = """
resource "aws_dynamodb_table" "sessions" {
  name = "sessions"
}
"""
    assert len(_check(src)) == 1


def test_flags_newly_allowlisted_azurerm_server():
    src = """
resource "azurerm_postgresql_flexible_server" "db" {
  name = "db"
}
"""
    assert len(_check(src)) == 1


def test_flags_protection_only_inside_settings():
    # Reproduced bug: `settings { deletion_protection_enabled }` is the API-side
    # flag two levels down; it does not stop `terraform destroy`.
    src = """
resource "google_sql_database_instance" "nested_only" {
  name = "prod"
  settings {
    tier                        = "db-f1-micro"
    deletion_protection_enabled = true
  }
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "only inside `settings`" in diags[0].message
    assert diags[0].line == 2


def test_nested_true_does_not_rescue_top_level_false():
    # The old flat scan took the first match in file order and passed this.
    src = """
resource "google_sql_database_instance" "main" {
  settings {
    deletion_protection_enabled = true
  }
  deletion_protection = false
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "deletion_protection = false" in diags[0].message


def test_top_level_flag_alongside_nested_one_is_protected():
    # The shape both real corpus Cloud SQL instances use.
    src = """
resource "google_sql_database_instance" "main" {
  deletion_protection = true
  settings {
    deletion_protection_enabled = true
  }
}
"""
    assert _check(src) == []


def test_prevent_destroy_outside_lifecycle_does_not_protect():
    src = """
resource "aws_db_instance" "x" {
  engine = "postgres"
  restore_to_point_in_time {
    prevent_destroy = true
  }
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "no deletion_protection" in diags[0].message


def test_prevent_destroy_in_a_nested_lifecycle_does_not_protect():
    src = """
resource "aws_db_instance" "x" {
  engine = "postgres"
  restore_to_point_in_time {
    lifecycle {
      prevent_destroy = true
    }
  }
}
"""
    assert len(_check(src)) == 1


def test_prevent_destroy_false_does_not_protect():
    src = """
resource "google_bigquery_dataset" "d" {
  dataset_id = "d"
  lifecycle {
    prevent_destroy = false
  }
}
"""
    assert len(_check(src)) == 1


def test_lifecycle_without_prevent_destroy_does_not_protect():
    src = """
resource "google_bigquery_dataset" "d" {
  dataset_id = "d"
  lifecycle {
    ignore_changes = [labels]
  }
}
"""
    assert len(_check(src)) == 1


def test_multiline_expression_value_is_unverifiable():
    src = """
resource "google_sql_database_instance" "main" {
  deletion_protection = (
    var.env == "prod"
  )
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "not a literal true" in diags[0].message


def test_multiline_false_is_disabled():
    # The old regex captured only the trailing `(` and passed every multi-line
    # value, including this one.
    src = """
resource "aws_rds_cluster" "c" {
  deletion_protection = (
    false
  )
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "deletion_protection = false" in diags[0].message


def test_commented_out_protection_does_not_protect():
    src = """
resource "google_sql_database_instance" "main" {
  # deletion_protection = true
  name = "prod"
}
"""
    assert len(_check(src)) == 1


def test_false_inside_a_heredoc_does_not_disable():
    src = """
resource "google_sql_database_instance" "main" {
  deletion_protection = true
  startup = <<-EOT
    deletion_protection = false
  EOT
}
"""
    assert _check(src) == []


def test_reports_the_resource_line_and_column():
    src = 'resource "google_sql_database_instance" "main" {\n  name = "prod"\n}\n'
    (diag,) = _check(src)
    assert (diag.line, diag.col) == (1, 1)


def test_allows_bigquery_view_without_deletion_protection():
    src = """
resource "google_bigquery_table" "daily_active_users" {
  dataset_id = "analytics"
  table_id   = "daily_active_users"
  view {
    query          = "SELECT user_id FROM `proj.analytics.events`"
    use_legacy_sql = false
  }
}
"""
    assert _check(src) == []


def test_allows_bigquery_materialized_view_without_deletion_protection():
    src = """
resource "google_bigquery_table" "rollup" {
  dataset_id = "analytics"
  materialized_view {
    query = "SELECT 1"
  }
}
"""
    assert _check(src) == []


def test_flags_bigquery_table_that_stores_data():
    """The boundary: a real table is retained — the guard keys on the view block."""
    src = """
resource "google_bigquery_table" "events" {
  dataset_id = "analytics"
  table_id   = "events"
  schema     = file("schema.json")
}
"""
    assert len(_check(src)) == 1


def test_flags_bigquery_table_whose_view_block_is_nested_elsewhere():
    """The boundary: only a DIRECT `view` child says the resource is a view."""
    src = """
resource "google_bigquery_table" "events" {
  dataset_id = "analytics"
  external_data_configuration {
    view {
      query = "SELECT 1"
    }
  }
}
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize("value", ["null", "NULL", "var.guard", "local.guard", "true && var.guard"])
def test_flags_null_or_unverifiable_protection(value: str):
    src = f"""resource "google_sql_database_instance" "main" {{
  deletion_protection = {value}
}}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "not a literal true" in diags[0].message


def test_tf_json_is_explicitly_out_of_scope():
    source = '{"resource":{"aws_db_instance":{"main":{"deletion_protection":false}}}}'

    assert _check(source, name="main.tf.json") == []


def test_still_flags_a_curated_type_next_to_the_removed_one():
    """The boundary: removing one type must not disturb the rest of the set."""
    src = """
resource "google_bigtable_instance" "main" {
  name = "prod"
}
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize("value", ["FALSE", "False", "fAlSe", '"FALSE"', "( FALSE )"])
def test_an_uppercase_false_is_still_disabled_protection(value: str):
    """`_literal` lowercases; without that, `deletion_protection = FALSE` reads as an expression."""
    src = f'resource "google_sql_database_instance" "main" {{\n  deletion_protection = {value}\n}}\n'
    diags = _check(src)
    assert len(diags) == 1
    assert "deletion_protection = false" in diags[0].message


@pytest.mark.parametrize("value", ["TRUE", "True", '"TRUE"'])
def test_an_uppercase_true_still_protects(value: str):
    """The other side: lowercasing must not turn a working guard into a finding."""
    src = f'resource "google_sql_database_instance" "main" {{\n  deletion_protection = {value}\n}}\n'
    assert _check(src) == []


def test_an_uppercase_prevent_destroy_still_protects():
    src = """
resource "google_bigquery_dataset" "warehouse" {
  dataset_id = "warehouse"
  lifecycle {
    prevent_destroy = TRUE
  }
}
"""
    assert _check(src) == []


@pytest.mark.parametrize("resource_type", sorted(PROTECTED_TYPES))
def test_every_protected_type_is_wired_in(resource_type: str):
    """Verify deleting any single row from PROTECTED_TYPES fails this test case."""
    src = f'resource "{resource_type}" "example" {{\n  name = "example"\n}}\n'
    diags = _check(src)
    if resource_type == "google_redis_instance":
        assert diags == []
    else:
        assert len(diags) == 1
        assert diags[0].code == "SARJ201"
        assert resource_type in diags[0].message


def test_the_curated_set_is_exactly_this():
    expected = {
        "google_sql_database_instance",
        "google_container_cluster",
        "google_bigquery_table",
        "google_bigquery_dataset",
        "google_spanner_database",
        "google_sql_database",
        "google_alloydb_cluster",
        "google_bigtable_instance",
        "google_redis_instance",
        "google_filestore_instance",
        "aws_db_instance",
        "aws_rds_cluster",
        "aws_rds_global_cluster",
        "aws_redshift_cluster",
        "aws_dynamodb_table",
        "aws_elasticache_replication_group",
        "aws_elasticache_cluster",
        "aws_docdb_cluster",
        "aws_neptune_cluster",
        "azurerm_postgresql_flexible_server",
        "azurerm_postgresql_server",
        "azurerm_mysql_flexible_server",
        "azurerm_mysql_server",
        "azurerm_mssql_server",
        "azurerm_mssql_database",
        "azurerm_cosmosdb_account",
    }
    assert expected == PROTECTED_TYPES
