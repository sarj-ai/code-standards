r"""SARJ201: stateful Terraform resources must keep `deletion_protection = true`.

A `terraform apply` (or `destroy`) that drops a database, cluster, or warehouse
is unrecoverable. Cloud providers expose a `deletion_protection` flag exactly to
make that mistake impossible without an explicit two-step removal; leaving it off
(or `= false`) means a stray plan can delete production data.

    # flagged — no deletion_protection
    resource "google_sql_database_instance" "main" {
      name = "prod"
    }

    # flagged — explicitly disabled
    resource "google_sql_database_instance" "main" {
      deletion_protection = false
    }

    # ok
    resource "google_sql_database_instance" "main" {
      deletion_protection = true
    }

Only resources that actually expose a `deletion_protection` argument are checked
(`PROTECTED_TYPES`). Buckets, secrets, and registries expose no such argument
and are deliberately absent — SARJ203 covers those via `prevent_destroy`.

Two curation corrections (2026-07)
----------------------------------
A 21-finding sample of the rule's 24 findings over 256 deduped `.tf` files read
TP 8 / FP 9 / arguable 4 — 42.9% wrong, in exactly two classes.

* **BigQuery views are not tables.** 9 of the 24 findings were
  `google_bigquery_table` blocks, and every one but a single genuine events table
  carried a `view { query = ... }` block — hand-verified through `_hcl.blocks()`.
  A BigQuery view stores no data, so there is nothing for deletion protection to
  protect; worse, the provider *requires* `deletion_protection = false` on a view
  whose query can change, because updating the query replaces the resource and the
  replace fails at apply while protection is on. Taking this rule's advice breaks
  the stack. `google_bigquery_table` blocks with a direct `view` or
  `materialized_view` child are skipped; the one real table is retained, so recall
  cost is zero.
* **`google_redis_instance` does not expose the argument at all** — 4 of the 24.
  That contradicts this rule's own stated curation criterion two paragraphs up.
  The provider puts `deletion_protection_enabled` on `google_redis_cluster`, not
  on `google_redis_instance`, so the advice was unfollowable; and a Memorystore
  cache is not a system of record in the first place. It is removed from
  `PROTECTED_TYPES`.

Reads structure, not lines
--------------------------
The rule resolves the resource through `_hcl.blocks()` and consults only that
block's **direct** attributes and its **direct** `lifecycle` child. The previous
implementation flattened the resource to a list of lines and matched the first
`deletion_protection` anywhere inside it, which was nesting-blind and produced
two reproduced false negatives:

* **nested `settings` counted as protection.** `google_sql_database_instance`
  carries two different switches: instance-level `deletion_protection` (the
  Terraform-side guard that refuses `terraform destroy`) and
  `settings.deletion_protection_enabled` (the API-side guard), two levels down.
  A resource declaring only the nested one was silently accepted. Worse, a
  resource declaring `settings { deletion_protection_enabled = true }` *and*
  top-level `deletion_protection = false` was also accepted, because the nested
  line came first in file order and won. The Terraform-side guard is the one
  that stops a plan, so a resource that leaves it off is judged, with a message
  naming the nested block so the fix is obvious,
* **`prevent_destroy` in any sub-block counted.** `prevent_destroy` is only
  meaningful inside `lifecycle`; the flat scan honoured it inside any nested
  block, so a `restore_to_point_in_time { prevent_destroy = true }` passed a
  wide-open `aws_db_instance`. Only a direct `lifecycle` child counts now.

Both real Cloud SQL instances in the audited corpus declare *both* switches —
one in repo A's IaC tree (a literal `deletion_protection = true`, a
`lifecycle.prevent_destroy`, and a nested `settings.deletion_protection_enabled`
on the same resource) and one in repo B's (var-gated at the top level, nested
flag below) — so both stay clean. The nesting bugs were latent, not endemic:
corpus counts are unchanged (0 in repo A, 18 in repo B) and no finding of either
new kind appeared. They are pinned by fixture instead. (The two IaC corpora are
written as repo A and repo B throughout this docstring.)

Multi-line values
-----------------
`_hcl.blocks()` rejoins a value split across lines, so
`deletion_protection = (\n  var.env == "prod"\n)` is read as the expression it
is. The old regex captured only the trailing `(` and, because `(` is not the
string `false`, classified *every* multi-line value as protected — including
`deletion_protection = (\n  false\n)`, which is now correctly flagged as
disabled. (The audit reported the opposite symptom, "treated as missing"; that
never reproduced — the defect was an unconditional pass, not a false alarm.)

Guards, all deliberate
----------------------
* **an expression-valued flag is protection, not a violation.** Anything not
  literally `false` passes: `deletion_protection = var.enable_deletion_protection`
  is the standard per-environment pattern and is how nearly every protected
  resource in both corpora is written — four such sites, two in repo B (a Cloud
  SQL instance and a media-processing cluster) and two in repo A (a GKE cluster
  and a GKE data-plane service). A rule demanding a literal `true`
  would be wrong on 4 of the 7 protected resources in the corpus,
* `"false"` (quoted) and `( false )` (parenthesised) still read as `false`,
* `lifecycle { prevent_destroy = true }` protects on its own — it is the only
  guard `google_bigquery_dataset` has, and it is how repo A protects its one
  dataset. Terraform requires
  `prevent_destroy` to be a literal, so only literal `true` counts; a
  `prevent_destroy = false` (one site in repo A) does not,
* comments and heredoc bodies never reach the parser, so a `}` inside a string
  or a `deletion_protection = false` inside a heredoc script can neither shear
  the block nor fake a value.

Suppress a deliberate ephemeral resource with `# sarj-noqa: SARJ201 — <reason>`
on the `resource` line.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import blocks
from sarj_iac_lint.rule_base import Diagnostic, Rule


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_iac_lint._hcl import Block

# Curated set of stateful resources whose accidental destroy is unrecoverable
# AND which expose a `deletion_protection[_enabled]` argument. Resources with no
# such argument (buckets, secrets, registries) belong to SARJ203, not here.
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
        # `google_redis_instance` deliberately absent: the provider exposes no
        # `deletion_protection` argument on it (the flag lives on
        # `google_redis_cluster` as `deletion_protection_enabled`), so the
        # diagnostic named a fix that cannot be written.
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
        """Flag protected-type resources whose own block declares no working guard.

        Returns:
            One diagnostic per unprotected resource, in source order.

        """
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
    """Report whether `block` is a `google_bigquery_table` that declares a view.

    Only a **direct** `view` / `materialized_view` child counts, for the same
    reason `_violation` reads only direct attributes: a nested block elsewhere in
    the resource says nothing about what the resource is.

    Returns:
        True when the resource is a BigQuery view rather than a stored table.

    """
    if block.labels[0] != _BIGQUERY_TABLE:
        return False
    return any(block.child(name) is not None for name in _VIEW_CHILDREN)


def _violation(block: Block) -> str | None:
    """Describe why `block` is unprotected, or None when it is protected.

    Only the resource's own attributes and its direct `lifecycle` child are
    consulted — a flag buried in a nested block does not stop `terraform
    destroy` from tearing the resource down.

    Returns:
        A short detail phrase for the diagnostic, or None when protected.

    """
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
    """Name the sub-block holding a protection flag that does not guard `block`.

    Returns:
        The dotted path of the nesting sub-block (e.g. `settings`), else None.

    """
    for child in block.blocks:
        attr = child.attribute(*_PROTECTION_ATTRS)
        if attr is not None and _literal(attr.value) != "false":
            return child.type
        deeper = _nested_protection(child)
        if deeper is not None:
            return f"{child.type}.{deeper}"
    return None


def _literal(value: str) -> str:
    """Reduce an attribute value to its bare literal for a `true`/`false` test.

    Strips a trailing comma, redundant wrapping parentheses (a multi-line value
    arrives as `( ... )`), and quotes — `"false"` and `( false )` both mean
    `false`. Anything else comes back as written and so matches neither literal.

    Returns:
        The lowercased bare literal, or the value unchanged when it is an
        expression.

    """
    text = value.strip().rstrip(",").strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text.strip('"').strip().lower()
