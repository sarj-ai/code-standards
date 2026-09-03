from __future__ import annotations

from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import blocks
from sarj_iac_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_iac_lint._hcl import Block

# Stateful resources exposing deletion_protection[_enabled].
PROTECTED_TYPES = frozenset(
    {
        # GCP
        "google_sql_database_instance",
        "google_sql_database",
        "google_container_cluster",
        "google_bigquery_table",
        "google_bigquery_dataset",
        "google_spanner_database",
        "google_alloydb_cluster",
        "google_bigtable_instance",
        "google_redis_instance",
        "google_filestore_instance",
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

_RESOURCE_PROTECTION_ATTRS: MappingProxyType[str, tuple[str, ...]] = MappingProxyType(
    {
        "google_sql_database_instance": ("deletion_protection",),
        "google_sql_database": (),
        "google_container_cluster": ("deletion_protection",),
        "google_bigquery_table": ("deletion_protection",),
        "google_bigquery_dataset": (),
        "google_spanner_database": ("deletion_protection",),
        "google_alloydb_cluster": (),
        "google_bigtable_instance": ("deletion_protection",),
        "google_redis_instance": ("deletion_protection",),
        "google_filestore_instance": ("deletion_protection_enabled",),
        "aws_db_instance": ("deletion_protection",),
        "aws_rds_cluster": ("deletion_protection",),
        "aws_rds_global_cluster": ("deletion_protection",),
        "aws_redshift_cluster": (),
        "aws_dynamodb_table": ("deletion_protection_enabled",),
        "aws_elasticache_replication_group": (),
        "aws_elasticache_cluster": (),
        "aws_docdb_cluster": ("deletion_protection",),
        "aws_neptune_cluster": ("deletion_protection",),
        "azurerm_postgresql_flexible_server": (),
        "azurerm_postgresql_server": (),
        "azurerm_mysql_flexible_server": (),
        "azurerm_mysql_server": (),
        "azurerm_mssql_server": (),
        "azurerm_mssql_database": (),
        "azurerm_cosmosdb_account": (),
    }
)
_DELETION_POLICY_TYPES = frozenset(
    {
        "google_bigquery_dataset",
        "google_bigquery_table",
        "google_bigtable_instance",
        "google_container_cluster",
        "google_filestore_instance",
        "google_redis_instance",
        "google_spanner_database",
        "google_sql_database",
        "google_sql_database_instance",
    }
)
_DEFAULT_PROTECTED_TYPES = frozenset(
    {
        "google_bigquery_table",
        "google_bigtable_instance",
        "google_container_cluster",
        "google_redis_instance",
        "google_sql_database_instance",
    }
)
_DELETION_POLICY = "deletion_policy"

_FIXTURE_PARTS = frozenset({"fixture", "fixtures", "generated", "testdata"})


@final
class RequireDeletionProtection(Rule):
    id = "require-deletion-protection"
    code = "SARJ201"
    documentation = RuleDocumentation(
        summary=(
            "Warn when a curated stateful Terraform resource lacks a proven provider-native deletion guard or literal "
            "lifecycle destroy guard."
        ),
        rationale=(
            "Stateful services can lose durable production data when an accidental Terraform change or destroy is "
            "allowed to delete the backing resource."
        ),
        remediation=(
            "Use the exact provider guard supported by that resource. Where none exists, consider lifecycle "
            "{ prevent_destroy = true }, which no longer protects the resource after its block is removed."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only curated resource-specific guard spellings with stable provider semantics are recognized.",
            (
                "Provider versions can change defaults; unresolved expressions are advisory because protection cannot "
                "be proven within one file."
            ),
            (
                "A lifecycle prevent_destroy guard is accepted as Terraform plan-time protection but does not survive "
                "removal of the resource block."
            ),
        ),
        examples=(
            RuleExample(
                example_id="unguarded-child-database",
                title="Cloud SQL child database uses its deletable default",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "database.tf",
                        'resource "google_sql_database" "app" {\n'
                        '  name     = "app"\n'
                        "  instance = google_sql_database_instance.main.name\n"
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("database.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="protected-child-database",
                title="Cloud SQL child database uses its provider guard",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "database.tf",
                        'resource "google_sql_database" "app" {\n'
                        '  name            = "app"\n'
                        "  instance        = google_sql_database_instance.main.name\n"
                        '  deletion_policy = "PREVENT"\n'
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("database.tf"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix.lower() != ".tf" or any(part.lower() in _FIXTURE_PARTS for part in path.parts):
            return []
        diags: list[Diagnostic] = []
        try:
            top_level = blocks(source)
        except ValueError:
            return []
        for block in top_level:
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
                    message=f'resource "{rtype}" "{rname}" has {detail} — {_remediation_for(rtype)}',
                )
            )
        return diags


def _is_bigquery_view(block: Block) -> bool:
    if block.labels[0] != _BIGQUERY_TABLE:
        return False
    return any(block.child(name) is not None for name in _VIEW_CHILDREN)


def _violation(block: Block) -> str | None:
    lifecycle = block.child(_LIFECYCLE)
    if lifecycle is not None:
        guard = lifecycle.attribute(_PREVENT_DESTROY)
        if guard is not None and _literal(guard.value) == "true":
            return None
    resource_type = block.labels[0]
    if resource_type == "google_sql_database_instance" and _has_nested_literal_protection(block):
        return None
    policy_problem: str | None = None
    if resource_type in _DELETION_POLICY_TYPES:
        policy = block.attribute(_DELETION_POLICY)
        if policy is not None:
            if _quoted_literal(policy.value) == "PREVENT":
                return None
            policy_problem = f"deletion_policy = {policy.value.strip()} is not literal PREVENT"
    attrs = _RESOURCE_PROTECTION_ATTRS[resource_type]
    attr = block.attribute(*attrs)
    if attr is not None:
        literal = _literal(attr.value)
        if literal == "true":
            return None
        if literal == "false":
            return f"{attr.name} = false"
        return f"{attr.name} = {attr.value.strip()} is not a literal true"
    if policy_problem is not None:
        return policy_problem
    if resource_type in _DEFAULT_PROTECTED_TYPES:
        return None
    nested = _nested_protection(block)
    if nested is not None:
        return (
            f"deletion_protection only inside `{nested}` — that is the API-side flag; the "
            "instance-level argument, which is what refuses a terraform destroy, is missing"
        )
    return "no deletion_protection / prevent_destroy"


def _nested_protection(block: Block) -> str | None:
    for child in block.blocks:
        attr = child.attribute("deletion_protection", "deletion_protection_enabled")
        if attr is not None and _literal(attr.value) != "false":
            return child.type
        deeper = _nested_protection(child)
        if deeper is not None:
            return f"{child.type}.{deeper}"
    return None


def _has_nested_literal_protection(block: Block) -> bool:
    for child in block.blocks:
        attr = child.attribute("deletion_protection_enabled")
        if (attr is not None and _literal(attr.value) == "true") or _has_nested_literal_protection(child):
            return True
    return False


def _literal(value: str) -> str:
    text = value.strip().rstrip(",").strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text


def _quoted_literal(value: str) -> str | None:
    text = value.strip().rstrip(",").strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text[1:-1] if text.startswith('"') and text.endswith('"') else None


def _remediation_for(resource_type: str) -> str:
    options = [f"{name} = true" for name in _RESOURCE_PROTECTION_ATTRS[resource_type]]
    if resource_type in _DELETION_POLICY_TYPES:
        options.append('deletion_policy = "PREVENT"')
    options.append("lifecycle.prevent_destroy = true (plan-time only; removing the resource block removes this guard)")
    return "use " + " or ".join(options) + "."
