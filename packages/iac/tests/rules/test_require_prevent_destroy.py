"""SARJ203 — every guard pinned in both directions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_iac_lint.rules.require_deletion_protection import PROTECTED_TYPES
from sarj_iac_lint.rules.require_prevent_destroy import (
    IRREPLACEABLE_TYPES,
    RequirePreventDestroyOnIrreplaceable,
)


if TYPE_CHECKING:
    from sarj_iac_lint.rule_base import Diagnostic


def _check(source: str, name: str = "main.tf") -> list[Diagnostic]:
    return RequirePreventDestroyOnIrreplaceable().check(Path(name), source)


def test_type_lists_are_disjoint_from_sarj201():
    # A resource must never draw both diagnostics: SARJ201 owns the curated
    # stateful service set; SARJ203 owns the bucket/secret/registry set.
    assert not (IRREPLACEABLE_TYPES & PROTECTED_TYPES)


def test_flags_unguarded_secret():
    src = """
resource "google_secret_manager_secret" "openai_api_key" {
  secret_id = "openai-api-key"
  replication {
    auto {}
  }
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "no lifecycle block" in diags[0].message
    assert (diags[0].line, diags[0].col) == (2, 1)


def test_allows_prevent_destroy():
    src = """
resource "google_secret_manager_secret" "app_managed" {
  secret_id = "x"
  lifecycle {
    prevent_destroy = true
  }
}
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "resource_type",
    [
        "google_storage_bucket",
        "google_secret_manager_secret",
        "google_artifact_registry_repository",
    ],
)
def test_allows_documented_google_deletion_policy_prevent(resource_type: str):
    src = f"""resource "{resource_type}" "main" {{
  name            = "prod"
  deletion_policy = "PREVENT"
}}
"""
    assert _check(src) == []


@pytest.mark.parametrize("value", ['"DELETE"', '"ABANDON"', "var.deletion_policy", "null"])
def test_google_deletion_policy_must_be_literal_prevent(value: str):
    src = f"""resource "google_storage_bucket" "main" {{
  name            = "prod"
  deletion_policy = {value}
}}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "deletion_policy" in diags[0].message


def test_allows_secret_manager_deletion_protection_true():
    src = """resource "google_secret_manager_secret" "main" {
  secret_id           = "prod"
  deletion_protection = true
}
"""
    assert _check(src) == []


@pytest.mark.parametrize("value", ["false", "var.deletion_protection", "null"])
def test_secret_manager_deletion_protection_must_be_literal_true(value: str):
    src = f"""resource "google_secret_manager_secret" "main" {{
  secret_id           = "prod"
  deletion_protection = {value}
}}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "deletion_protection" in diags[0].message


def test_lifecycle_guard_overrides_unproven_google_provider_guards():
    src = """resource "google_secret_manager_secret" "main" {
  secret_id           = "prod"
  deletion_policy     = var.deletion_policy
  deletion_protection = false
  lifecycle {
    prevent_destroy = true
  }
}
"""
    assert _check(src) == []


def test_flags_lifecycle_without_prevent_destroy():
    src = """
resource "google_storage_bucket" "b" {
  name = "b"
  lifecycle {
    ignore_changes = [labels]
  }
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "without prevent_destroy" in diags[0].message


def test_flags_prevent_destroy_false():
    src = """
resource "google_storage_bucket" "b" {
  name = "b"
  lifecycle {
    prevent_destroy = false
  }
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "prevent_destroy = false" in diags[0].message


def test_force_destroy_true_exempts():
    src = """
resource "google_storage_bucket" "scratch" {
  name          = "scratch"
  force_destroy = true
}
"""
    assert _check(src) == []


def test_force_destroy_expression_does_not_exempt():
    src = """
resource "google_storage_bucket" "recordings" {
  name          = "recordings"
  force_destroy = !var.enable_deletion_protection
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "force_destroy is not literal true" in diags[0].message


@pytest.mark.parametrize("value", ["null", "NULL", "var.force_destroy", "local.disposable"])
def test_null_or_unknown_force_destroy_does_not_exempt(value: str):
    src = f"""resource "google_storage_bucket" "recordings" {{
  name          = "recordings"
  force_destroy = {value}
}}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "force_destroy is not literal true" in diags[0].message


def test_explicit_force_destroy_false_does_not_exempt():
    # That is the provider default and is silent at plan time.
    src = """
resource "google_storage_bucket" "blob" {
  name          = "blob"
  force_destroy = false
}
"""
    assert len(_check(src)) == 1


def test_terraform_managed_version_does_not_replace_destroy_protection():
    src = """
resource "google_secret_manager_secret" "db_password" {
  secret_id = "db-password"
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db.result
}
"""
    assert len(_check(src)) == 1


def test_version_for_a_different_secret_does_not_exempt():
    src = """
resource "google_secret_manager_secret" "unmanaged" {
  secret_id = "unmanaged"
}

resource "google_secret_manager_secret" "managed" {
  secret_id = "managed"
}

resource "google_secret_manager_secret_version" "managed" {
  secret      = google_secret_manager_secret.managed.id
  secret_data = var.value
}
"""
    diags = _check(src)
    assert len(diags) == 2


def test_version_guard_does_not_exempt_buckets():
    src = """
resource "google_storage_bucket" "b" {
  name = "b"
}

resource "google_secret_manager_secret_version" "v" {
  secret = google_secret_manager_secret.other.id
}
"""
    assert len(_check(src)) == 1


def test_ignores_types_with_their_own_deletion_protection():
    src = 'resource "google_sql_database_instance" "main" {\n  name = "prod"\n}\n'
    assert _check(src) == []


def test_ignores_non_tf_files():
    src = 'resource "google_secret_manager_secret" "s" {\n}\n'
    assert _check(src, name="notes.txt") == []


def test_tf_json_is_explicitly_out_of_scope():
    source = '{"resource":{"aws_s3_bucket":{"main":{"force_destroy":false}}}}'

    assert _check(source, name="main.tf.json") == []


def test_flags_each_unguarded_resource():
    src = """
resource "google_secret_manager_secret" "a" {
  secret_id = "a"
}
resource "google_artifact_registry_repository" "b" {
  repository_id = "b"
  lifecycle {
    prevent_destroy = true
  }
}
resource "google_storage_bucket" "c" {
  name = "c"
}
"""
    assert [d.line for d in _check(src)] == [2, 11]


@pytest.mark.parametrize("resource_type", sorted(IRREPLACEABLE_TYPES))
def test_every_irreplaceable_type_is_wired_in(resource_type: str):
    """Verify deleting any single row from IRREPLACEABLE_TYPES fails this test case."""
    src = f'resource "{resource_type}" "example" {{\n  name = "example"\n}}\n'
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ203"
    assert resource_type in diags[0].message


@pytest.mark.parametrize("resource_type", sorted(IRREPLACEABLE_TYPES))
def test_prevent_destroy_guards_every_irreplaceable_type(resource_type: str):
    """The other direction: the guard must be honoured for every row, not just the GCP ones."""
    src = f'resource "{resource_type}" "example" {{\n  name = "example"\n  lifecycle {{\n    prevent_destroy = true\n  }}\n}}\n'
    assert _check(src) == []


def test_the_curated_set_is_exactly_this():
    expected = {
        "google_storage_bucket",
        "google_secret_manager_secret",
        "google_artifact_registry_repository",
        "aws_s3_bucket",
        "aws_secretsmanager_secret",
        "aws_ecr_repository",
        "azurerm_storage_account",
        "azurerm_key_vault",
        "azurerm_container_registry",
    }
    assert expected == IRREPLACEABLE_TYPES


def test_an_uppercase_prevent_destroy_still_guards():
    src = """
resource "aws_s3_bucket" "artifacts" {
  bucket = "artifacts"
  lifecycle {
    prevent_destroy = TRUE
  }
}
"""
    assert _check(src) == []


def test_an_uppercase_force_destroy_false_still_does_not_exempt():
    """The other side: `FALSE` is the provider default, not a disposability statement."""
    src = 'resource "aws_s3_bucket" "blob" {\n  bucket        = "blob"\n  force_destroy = FALSE\n}\n'
    assert len(_check(src)) == 1
