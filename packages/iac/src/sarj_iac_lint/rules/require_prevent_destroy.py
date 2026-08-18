from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, NamedTuple, final, override

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

# Irreplaceable storage, secret, and registry resource types across GCP, AWS, and Azure.
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
_DELETION_POLICY = "deletion_policy"
_DELETION_PROTECTION = "deletion_protection"

_GOOGLE_DELETION_POLICY_TYPES = frozenset(
    {
        "google_storage_bucket",
        "google_secret_manager_secret",
        "google_artifact_registry_repository",
    }
)
_GOOGLE_DELETION_PROTECTION_TYPES = frozenset({"google_secret_manager_secret"})

_HCL_SUFFIXES = (".tf", ".hcl")


class _ProviderGuardResult(NamedTuple):
    protected: bool
    problem: str | None


@final
class RequirePreventDestroyOnIrreplaceable(Rule):
    id = "require-prevent-destroy-on-irreplaceable"
    code = "SARJ203"
    documentation = RuleDocumentation(
        summary=(
            "Bucket, secret, or artifact registry must use a supported literal provider-side "
            "deletion guard or lifecycle { prevent_destroy = true }."
        ),
        rationale=(
            "Buckets, secrets, and registries contain state that is difficult or impossible to reconstruct after an "
            "accidental infrastructure destroy."
        ),
        remediation=("Use a supported literal provider deletion guard, or add lifecycle { prevent_destroy = true }."),
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only the curated resource types and documented Google provider guards are recognized.",
            "A literal force_destroy = true is treated as an explicit declaration that the resource is disposable.",
        ),
        examples=(
            RuleExample(
                example_id="unguarded-bucket",
                title="Irreplaceable bucket without a deletion guard",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "storage.tf",
                        'resource "google_storage_bucket" "records" {\n  name = "records"\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("storage.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="protected-bucket",
                title="Irreplaceable bucket protected at plan time",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "storage.tf",
                        'resource "google_storage_bucket" "records" {\n'
                        '  name = "records"\n'
                        "  lifecycle {\n"
                        "    prevent_destroy = true\n"
                        "  }\n"
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("storage.tf"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
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
                        f'resource "{rtype}" "{rname}" is irreplaceable and {detail} — use a supported '
                        "literal provider-side deletion guard where available, or add "
                        "lifecycle { prevent_destroy = true } to make a destroy fail at plan time."
                    ),
                )
            )
        return diags


def _violation(block: Block) -> str | None:
    force = block.attribute(_FORCE_DESTROY)
    if force is not None and _literal(force.value) == "true":
        # A literal true is an explicit declaration that the store is disposable.
        return None
    provider_guard = _provider_guard(block)
    if provider_guard.protected:
        return None
    lifecycle = block.child(_LIFECYCLE)
    if lifecycle is None:
        if force is not None and _literal(force.value) != "false":
            return f"has force_destroy = {force.value.strip()}, but force_destroy is not literal true"
        if provider_guard.problem is not None:
            return provider_guard.problem
        if block.labels[0] in _GOOGLE_DELETION_POLICY_TYPES:
            return "has no provider-side deletion guard and no lifecycle block"
        return "has no lifecycle block"
    guard = lifecycle.attribute(_PREVENT_DESTROY)
    if guard is None:
        return "has a lifecycle block without prevent_destroy"
    return (
        None
        if _literal(guard.value) == "true"
        else f"sets prevent_destroy = {guard.value.strip()}, which is not literal true"
    )


def _provider_guard(block: Block) -> _ProviderGuardResult:
    resource_type = block.labels[0]
    problems: list[str] = []
    if resource_type in _GOOGLE_DELETION_POLICY_TYPES:
        policy = block.attribute(_DELETION_POLICY)
        if policy is not None:
            if _quoted_literal(policy.value) == "PREVENT":
                return _ProviderGuardResult(protected=True, problem=None)
            problems.append(f"sets deletion_policy = {policy.value.strip()}, which is not literal PREVENT")
    if resource_type in _GOOGLE_DELETION_PROTECTION_TYPES:
        protection = block.attribute(_DELETION_PROTECTION)
        if protection is not None:
            if _literal(protection.value) == "true":
                return _ProviderGuardResult(protected=True, problem=None)
            problems.append(f"sets deletion_protection = {protection.value.strip()}, which is not literal true")
    return _ProviderGuardResult(protected=False, problem="; and ".join(problems) if problems else None)


def _literal(value: str) -> str:
    text = value.strip().rstrip(",").strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text.strip('"').strip().lower()


def _quoted_literal(value: str) -> str | None:
    text = value.strip().rstrip(",").strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text[1:-1] if text.startswith('"') and text.endswith('"') else None
