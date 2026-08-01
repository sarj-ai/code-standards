"""SARJ203: irreplaceable resources with no `deletion_protection` need `prevent_destroy`.

SARJ201 protects stores that expose a provider-side `deletion_protection`
argument. Buckets, Secret Manager secrets, and artifact registries expose no
such argument at all — which is exactly why SARJ201's curated type list omits
them, and why nothing was guarding them. Their contents are still
unrecoverable: a destroyed secret takes every version with it, a destroyed
bucket takes its objects, a destroyed registry takes every image digest a
rollback might need.

Terraform's own mechanism for that class is `lifecycle { prevent_destroy =
true }`, which fails the *plan* rather than the apply. No OSS Terraform linter
checks it — tfsec, checkov and tflint all reason about provider arguments and
resource configuration, not about `lifecycle` meta-arguments — so this gap is
not covered by anything already in the pipeline.

    # flagged
    resource "google_secret_manager_secret" "openai_api_key" {
      secret_id = "openai-api-key"
      replication { auto {} }
    }

    # ok
    resource "google_secret_manager_secret" "app_managed" {
      secret_id = each.key
      replication { auto {} }
      lifecycle {
        prevent_destroy = true
      }
    }

This codifies a convention the audited repos already chose rather than
importing an outside opinion: 5 of repo A's 6 `google_storage_bucket`s and its
one `google_artifact_registry_repository` already carry `prevent_destroy = true`
(two blob buckets and the CI artifact registry), as does its shared secret
family. The rule makes the outliers visible. (The two IaC corpora are written as
repo A and repo B throughout this docstring.)

Measured
--------
29 resources of these types across the two corpora; 15 fire — 1 in repo A
and 14 in repo B — every one hand-checked below. The remaining 14 are
either already guarded or hit a guard.

Guards, each derived from a finding that would otherwise have been wrong
-----------------------------------------------------------------------
* **`force_destroy` set to anything but a literal `false` exempts the
  resource.** `force_destroy = true` is an unambiguous "wipe this, contents and
  all"; an *expression* is an environment-gated destroy policy, and
  `prevent_destroy` cannot express it because Terraform requires that
  meta-argument to be a literal. One bucket in repo B writes
  `force_destroy = !var.enable_deletion_protection` on a media-recordings bucket
  whose own `lifecycle_rule`s delete objects after 90 days — demanding a literal
  `prevent_destroy = true` there would break the non-prod teardown the author
  deliberately built. An explicit `force_destroy = false` is the provider
  default and does **not** exempt: it only makes a destroy *error* when the
  bucket happens to be non-empty, and it is silent at plan time,
* **a secret whose value Terraform owns is replaceable, so it is exempt.** When
  a `google_secret_manager_secret_version` (or `aws_secretsmanager_secret_version`)
  in the same file feeds this secret, `terraform apply` reconstructs the value
  after a destroy and nothing is lost — the rule's whole predicate fails. This
  is not hypothetical: it accounts for 6 of the 21 resources that the guard-free
  version of this rule flagged, and every one would have been a false positive.
  In repo A one service secret is fed from a `random_password.<name>.result`,
  which is stable in state; one IAM secret from a `google_service_account_key`;
  and two data-plane secrets from a `google_storage_hmac_key`. In repo B two
  secrets are fed from a composed database URL. The 14 repo-B secrets that DO
  fire have no version resource anywhere — they are third-party API keys and TLS
  material populated out of band, so a destroy is unrecoverable from code,
* the lookup is **per file**, like every rule in this package. A version
  declared in a different file than its secret is not seen, so that shape
  over-reports; suppress it with `# sarj-noqa: SARJ203 — <reason>` on the
  `resource` line. No such split exists in either corpus.

Deliberately NOT covered
------------------------
* anything SARJ201 already judges — the two type lists are disjoint by
  construction, so no resource can draw both diagnostics,
* KMS key rings and crypto keys. GCP refuses to delete either; `terraform
  destroy` only drops them from state, so there is no data to lose and
  `prevent_destroy` would be cargo cult,
* `google_storage_bucket_object`, IAM bindings, and other resources that are
  pure projections of a source of truth held elsewhere.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import blocks
from sarj_iac_lint.rule_base import Diagnostic, Rule


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_iac_lint._hcl import Block

# Stores that expose NO provider-side deletion_protection argument, so
# `lifecycle.prevent_destroy` is the only guard Terraform offers. GCP entries
# are measured in the audited corpora; the AWS/Azure rows are the identical
# shape (irreversible destroy, no protection argument) on the other clouds.
IRREPLACEABLE_TYPES = frozenset(
    {
        # GCP
        "google_storage_bucket",
        "google_secret_manager_secret",
        "google_artifact_registry_repository",
        # AWS
        "aws_s3_bucket",
        "aws_secretsmanager_secret",
        "aws_ecr_repository",
        # Azure
        "azurerm_storage_account",
        "azurerm_key_vault",
        "azurerm_container_registry",
    }
)

# `<version resource type>: <secret resource type it supplies>`. A secret fed by
# one of these is reconstructable by `terraform apply`, hence not irreplaceable.
_VERSION_SOURCES = {
    "google_secret_manager_secret_version": "google_secret_manager_secret",
    "aws_secretsmanager_secret_version": "aws_secretsmanager_secret",
}

_RESOURCE = "resource"
_LIFECYCLE = "lifecycle"
_PREVENT_DESTROY = "prevent_destroy"
_FORCE_DESTROY = "force_destroy"

# A `<resource_type>.<resource_name>` traversal inside an attribute value.
_REFERENCE_RE = re.compile(r"\b([a-z][a-z0-9_]*)\.([A-Za-z_][\w-]*)")

_HCL_SUFFIXES = (".tf", ".tf.json", ".hcl")


@final
class RequirePreventDestroyOnIrreplaceable(Rule):
    """Bucket / secret / registry with no lifecycle.prevent_destroy guard."""

    id = "require-prevent-destroy-on-irreplaceable"
    code = "SARJ203"
    description = (
        "Bucket, secret, or artifact registry exposes no deletion_protection — "
        "guard it with lifecycle { prevent_destroy = true } so a plan cannot destroy it."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag irreplaceable stores lacking `lifecycle { prevent_destroy = true }`.

        Returns:
            One diagnostic per unguarded resource, in source order.

        """
        if not str(path).endswith(_HCL_SUFFIXES):
            return []
        top = blocks(source)
        reconstructable = _terraform_owned_secrets(top)
        diags: list[Diagnostic] = []
        for block in top:
            if block.type != _RESOURCE or not block.labels or block.labels[0] not in IRREPLACEABLE_TYPES:
                continue
            if (block.labels[0], block.labels[-1]) in reconstructable:
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
                        f'resource "{rtype}" "{rname}" is irreplaceable and {detail} — it exposes no '
                        "deletion_protection argument, so add lifecycle { prevent_destroy = true } "
                        "to make a destroy fail at plan time."
                    ),
                )
            )
        return diags


def _violation(block: Block) -> str | None:
    """Describe why `block` is unguarded, or None when it is guarded or exempt.

    Returns:
        A short detail phrase for the diagnostic, or None when no diagnostic is
        warranted.

    """
    force = block.attribute(_FORCE_DESTROY)
    if force is not None and _literal(force.value) != "false":
        # `force_destroy = true`, or an env-gated expression `prevent_destroy`
        # cannot mirror — a deliberate statement that this store is disposable.
        return None
    lifecycle = block.child(_LIFECYCLE)
    if lifecycle is None:
        return "has no lifecycle block"
    guard = lifecycle.attribute(_PREVENT_DESTROY)
    if guard is None:
        return "has a lifecycle block without prevent_destroy"
    return None if _literal(guard.value) == "true" else "sets prevent_destroy = false"


def _terraform_owned_secrets(top: tuple[Block, ...]) -> frozenset[tuple[str, str]]:
    """Collect `(secret_type, secret_name)` pairs whose value Terraform reconstructs.

    A `*_secret_version` resource in this file that references a secret means a
    destroy of that secret is recoverable by `terraform apply`.

    Returns:
        The set of secrets that are not irreplaceable.

    """
    owned: set[tuple[str, str]] = set()
    for block in top:
        if block.type != _RESOURCE or not block.labels:
            continue
        secret_type = _VERSION_SOURCES.get(block.labels[0])
        if secret_type is None:
            continue
        owned.update(
            (secret_type, m.group(2))
            for attr in block.attributes
            for m in _REFERENCE_RE.finditer(attr.value)
            if m.group(1) == secret_type
        )
    return frozenset(owned)


def _literal(value: str) -> str:
    """Reduce an attribute value to its bare literal for a `true`/`false` test.

    Returns:
        The lowercased bare literal, or the value unchanged when it is an
        expression.

    """
    text = value.strip().rstrip(",").strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text.strip('"').strip().lower()
