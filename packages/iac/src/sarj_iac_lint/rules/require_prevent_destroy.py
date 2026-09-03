from __future__ import annotations

from pathlib import PurePosixPath
from types import MappingProxyType
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

_DESTRUCTIVE_ATTRIBUTES: MappingProxyType[str, tuple[str, ...]] = MappingProxyType(
    {
        "aws_ecr_repository": ("force_delete",),
        "aws_s3_bucket": ("force_destroy",),
        "google_storage_bucket": ("force_destroy",),
    }
)
_FIXTURE_PARTS = frozenset({"fixture", "fixtures", "generated", "testdata"})


class _ProviderGuardResult(NamedTuple):
    protected: bool
    problem: str | None


@final
class RequirePreventDestroyOnIrreplaceable(Rule):
    id = "require-prevent-destroy-on-irreplaceable"
    code = "SARJ203"
    documentation = RuleDocumentation(
        summary=(
            "Warn when a curated durable-data container lacks a literal provider-side deletion guard or Terraform "
            "lifecycle destroy guard."
        ),
        rationale=(
            "Buckets, secrets, and registries may hold durable state; unguarded deletion needs review when no "
            "authoritative recovery source exists."
        ),
        remediation=(
            "Prefer a supported provider guard. Otherwise consider lifecycle { prevent_destroy = true }, which stops "
            "planned deletion only while the resource block remains, or suppress SARJ203 with a disposable rationale."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only the curated resource types and documented Google provider guards are recognized.",
            "Provider controls are version-sensitive; unsupported or dynamic guard expressions do not prove safety.",
            (
                "Terraform lifecycle.prevent_destroy is plan-time protection and does not survive removal of the "
                "resource block."
            ),
        ),
        examples=(
            RuleExample(
                example_id="unguarded-bucket",
                title="Durable-data bucket without a deletion guard",
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
                title="Durable-data bucket protected by provider policy",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "storage.tf",
                        'resource "google_storage_bucket" "records" {\n'
                        '  name = "records"\n'
                        '  deletion_policy = "PREVENT"\n'
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("storage.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="destructive-unguarded-bucket",
                title="Force deletion is not a disposable-resource declaration",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "storage.tf",
                        'resource "google_storage_bucket" "records" {\n'
                        '  name          = "records"\n'
                        "  force_destroy = true\n"
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("storage.tf"),
                expected_count=1,
                scenario="destructive-setting",
                public=True,
            ),
            RuleExample(
                example_id="destructive-provider-guarded-bucket",
                title="Provider policy still blocks a force-enabled deletion",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "storage.tf",
                        'resource "google_storage_bucket" "records" {\n'
                        '  name            = "records"\n'
                        "  force_destroy   = true\n"
                        '  deletion_policy = "PREVENT"\n'
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("storage.tf"),
                expected_count=0,
                scenario="destructive-setting",
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix.lower() != ".tf" or any(part.lower() in _FIXTURE_PARTS for part in path.parts):
            return []
        try:
            top = blocks(source)
        except ValueError:
            return []
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
                        f'resource "{rtype}" "{rname}" may contain durable data and {detail} — '
                        f"{_remediation_for(rtype)}"
                    ),
                )
            )
        return diags


def _violation(block: Block) -> str | None:
    provider_guard = _provider_guard(block)
    if provider_guard.protected:
        return None
    destructive_problem = _destructive_problem(block)
    lifecycle = block.child(_LIFECYCLE)
    if lifecycle is None:
        if destructive_problem is not None:
            return destructive_problem
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
    return text


def _quoted_literal(value: str) -> str | None:
    text = value.strip().rstrip(",").strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text[1:-1] if text.startswith('"') and text.endswith('"') else None


def _destructive_problem(block: Block) -> str | None:
    for name in _DESTRUCTIVE_ATTRIBUTES.get(block.labels[0], ()):
        attribute = block.attribute(name)
        if attribute is None:
            continue
        if _literal(attribute.value) == "true":
            return f"sets {name} = true, allowing contained data to be deleted during destroy"
        if _literal(attribute.value) != "false":
            return f"sets {name} = {attribute.value.strip()}, whose destructive behavior is unresolved"
    return None


def _remediation_for(resource_type: str) -> str:
    options: list[str] = []
    if resource_type in _GOOGLE_DELETION_POLICY_TYPES:
        options.append('set deletion_policy = "PREVENT"')
    if resource_type in _GOOGLE_DELETION_PROTECTION_TYPES:
        options.append("set deletion_protection = true")
    options.extend(
        (
            "use lifecycle.prevent_destroy = true for plan-time protection (removing the resource block removes it)",
            "suppress SARJ203 with a reviewed disposable-resource rationale",
        )
    )
    return ", or ".join(options) + "."
