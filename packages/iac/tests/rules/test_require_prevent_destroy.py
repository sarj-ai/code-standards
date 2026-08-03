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
    # A resource must never draw both diagnostics: SARJ201 covers types with a
    # deletion_protection argument, SARJ203 covers types without one.
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


# --- guard: force_destroy ---------------------------------------------------


def test_force_destroy_true_exempts():
    src = """
resource "google_storage_bucket" "scratch" {
  name          = "scratch"
  force_destroy = true
}
"""
    assert _check(src) == []


def test_force_destroy_expression_exempts():
    # `prevent_destroy` must be a literal, so it cannot express this env gate.
    src = """
resource "google_storage_bucket" "recordings" {
  name          = "recordings"
  force_destroy = !var.enable_deletion_protection
}
"""
    assert _check(src) == []


def test_explicit_force_destroy_false_does_not_exempt():
    # That is the provider default and is silent at plan time.
    src = """
resource "google_storage_bucket" "blob" {
  name          = "blob"
  force_destroy = false
}
"""
    assert len(_check(src)) == 1


# --- guard: a secret whose value Terraform reconstructs ---------------------


def test_terraform_managed_version_exempts_the_secret():
    src = """
resource "google_secret_manager_secret" "db_password" {
  secret_id = "db-password"
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db.result
}
"""
    assert _check(src) == []


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
    assert len(diags) == 1
    assert "unmanaged" in diags[0].message


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


# --- scope ------------------------------------------------------------------


def test_ignores_types_with_their_own_deletion_protection():
    src = 'resource "google_sql_database_instance" "main" {\n  name = "prod"\n}\n'
    assert _check(src) == []


def test_ignores_non_tf_files():
    src = 'resource "google_secret_manager_secret" "s" {\n}\n'
    assert _check(src, name="notes.txt") == []


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


# --- every curated type must be reachable, so no row can be dropped in silence -----


@pytest.mark.parametrize("resource_type", sorted(IRREPLACEABLE_TYPES))
def test_every_irreplaceable_type_is_wired_in(resource_type: str):
    """Deleting any single row from IRREPLACEABLE_TYPES fails exactly this row's case.

    Only the three GCP rows were reachable from a test before this, so the AWS and
    Azure halves of the set were decoration: removing `aws_s3_bucket` changed no
    result.
    """
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
    """Parametrizing over the set cannot catch a *deletion* — the case vanishes with the row.

    So the set is also pinned literally. Adding or removing a cloud's row is a
    policy change and must be a deliberate edit here, not a silent one.
    """
    expected = frozenset(
        {
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
    )
    assert expected == IRREPLACEABLE_TYPES


# --- HCL keywords are case-insensitive, so the literal test must be too ------------


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
