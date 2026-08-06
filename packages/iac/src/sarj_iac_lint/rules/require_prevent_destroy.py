"""SARJ203: Bucket, secret, or artifact registry with no deletion_protection requires lifecycle.prevent_destroy."""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import blocks
from sarj_iac_lint.rule_base import Diagnostic, Rule


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_iac_lint._hcl import Block

# Resource types lacking provider-side deletion_protection across GCP, AWS, and Azure.
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

_RESOURCE = "resource"
_LIFECYCLE = "lifecycle"
_PREVENT_DESTROY = "prevent_destroy"
_FORCE_DESTROY = "force_destroy"

_HCL_SUFFIXES = (".tf", ".hcl")


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
        """Flag irreplaceable stores lacking `lifecycle { prevent_destroy = true }`."""
        if not str(path).endswith(_HCL_SUFFIXES):
            return []
        top = blocks(source)
        diags: list[Diagnostic] = []
        for block in top:
            if block.type != _RESOURCE or not block.labels or block.labels[0] not in IRREPLACEABLE_TYPES:
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
    """Describe why `block` is unguarded, or None when it is guarded or exempt."""
    force = block.attribute(_FORCE_DESTROY)
    if force is not None and _literal(force.value) == "true":
        # A literal true is an explicit declaration that the store is disposable.
        return None
    lifecycle = block.child(_LIFECYCLE)
    if lifecycle is None:
        if force is not None and _literal(force.value) != "false":
            return f"has force_destroy = {force.value.strip()}, but force_destroy is not literal true"
        return "has no lifecycle block"
    guard = lifecycle.attribute(_PREVENT_DESTROY)
    if guard is None:
        return "has a lifecycle block without prevent_destroy"
    return None if _literal(guard.value) == "true" else "sets prevent_destroy = false"


def _literal(value: str) -> str:
    """Reduce an attribute value to its bare literal for a `true`/`false` test."""
    text = value.strip().rstrip(",").strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text.strip('"').strip().lower()
