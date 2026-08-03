"""SARJ201: Stateful Terraform resources must keep deletion_protection = true."""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import blocks
from sarj_iac_lint.rule_base import Diagnostic, Rule


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_iac_lint._hcl import Block

# Stateful resources with unrecoverable deletion risk exposing deletion_protection[_enabled] (google_redis_instance omitted).
PROTECTED_TYPES = frozenset(
    {
        # GCP
        "google_sql_database_instance",
        "google_container_cluster",
        "google_bigquery_table",
        "google_bigquery_dataset",
        "google_spanner_database",
        "google_alloydb_cluster",
        "google_bigtable_instance",
        # AWS
        "aws_db_instance",
        "aws_rds_cluster",
        "aws_rds_global_cluster",
        "aws_redshift_cluster",
        "aws_dynamodb_table",
        "aws_elasticache_replication_group",
        "aws_elasticache_cluster",
        "aws_docdb_cluster",
        "aws_neptune_cluster",
        # Azure
        "azurerm_postgresql_flexible_server",
        "azurerm_postgresql_server",
        "azurerm_mysql_flexible_server",
        "azurerm_mysql_server",
        "azurerm_mssql_server",
        "azurerm_mssql_database",
        "azurerm_cosmosdb_account",
    }
)

_RESOURCE = "resource"
_LIFECYCLE = "lifecycle"
_PREVENT_DESTROY = "prevent_destroy"

# A `google_bigquery_table` carrying one of these children is a view, not a table:
# it stores no rows, and the provider requires `deletion_protection = false` for a
# view whose query can be updated, since the update is a replace.
_BIGQUERY_TABLE = "google_bigquery_table"
_VIEW_CHILDREN = ("view", "materialized_view")

# Both spellings are legitimate *instance-level* argument names across providers.
_PROTECTION_ATTRS = ("deletion_protection", "deletion_protection_enabled")

_HCL_SUFFIXES = (".tf", ".tf.json", ".hcl")


@final
class RequireDeletionProtection(Rule):
    """Stateful resource without deletion_protection = true."""

    id = "require-deletion-protection"
    code = "SARJ201"
    description = (
        "Stateful resource (Cloud SQL, GKE, BigQuery, RDS, ...) must set "
        "deletion_protection = true so a stray apply cannot destroy prod data."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag protected-type resources whose own block declares no working guard."""
        if not str(path).endswith(_HCL_SUFFIXES):
            return []
        diags: list[Diagnostic] = []
        for block in blocks(source):
            if block.type != _RESOURCE or not block.labels or block.labels[0] not in PROTECTED_TYPES:
                continue
            if _is_bigquery_view(block):
                continue
            detail = _violation(block)
            if detail is None:
                continue
            rtype, rname = block.labels[0], block.labels[-1]
            diags.append(
                Diagnostic(
                    path=path,
                    line=block.line,
                    col=block.col,
                    code=self.code,
                    message=(
                        f'resource "{rtype}" "{rname}" has {detail} — keep '
                        "deletion_protection = true (or lifecycle.prevent_destroy) "
                        "so a stray apply/destroy cannot wipe prod data."
                    ),
                )
            )
        return diags


def _is_bigquery_view(block: Block) -> bool:
    """Report whether `block` is a `google_bigquery_table` that declares a view."""
    if block.labels[0] != _BIGQUERY_TABLE:
        return False
    return any(block.child(name) is not None for name in _VIEW_CHILDREN)


def _violation(block: Block) -> str | None:
    """Describe why `block` is unprotected, or None when it is protected."""
    attr = block.attribute(*_PROTECTION_ATTRS)
    if attr is not None:
        return f"{attr.name} = false" if _literal(attr.value) == "false" else None
    lifecycle = block.child(_LIFECYCLE)
    if lifecycle is not None:
        guard = lifecycle.attribute(_PREVENT_DESTROY)
        if guard is not None and _literal(guard.value) == "true":
            return None
    nested = _nested_protection(block)
    if nested is not None:
        return (
            f"deletion_protection only inside `{nested}` — that is the API-side flag; the "
            "instance-level argument, which is what refuses a terraform destroy, is missing"
        )
    return "no deletion_protection / prevent_destroy"


def _nested_protection(block: Block) -> str | None:
    """Name the sub-block holding a protection flag that does not guard `block`."""
    for child in block.blocks:
        attr = child.attribute(*_PROTECTION_ATTRS)
        if attr is not None and _literal(attr.value) != "false":
            return child.type
        deeper = _nested_protection(child)
        if deeper is not None:
            return f"{child.type}.{deeper}"
    return None


def _literal(value: str) -> str:
    """Reduce an attribute value to its bare literal for a `true`/`false` test."""
    text = value.strip().rstrip(",").strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text.strip('"').strip().lower()
