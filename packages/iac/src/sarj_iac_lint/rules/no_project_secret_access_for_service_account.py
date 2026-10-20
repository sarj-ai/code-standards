from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import tokens
from sarj_iac_lint.rule_base import (
    AutofixPolicy,
    DefaultLevel,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)
from sarj_iac_lint.rules._literal_policy import balanced_blocks, grant_roles, local_collections


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_iac_lint._hcl import Block


_SECRET_ROLES = frozenset({"roles/secretmanager.secretAccessor", "roles/secretmanager.admin"})
_GRANTS = frozenset({"google_project_iam_member", "google_project_iam_binding"})
_SERVICE_ACCOUNT_PREFIX = '"serviceAccount:'


@final
class NoProjectSecretAccessForServiceAccount(Rule):
    id = "no-project-secret-access-for-service-account"
    code = "SARJ213"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="Grant service accounts Secret Manager access per secret, not on the project.",
        rationale=(
            "A project-level Secret Manager accessor grant lets the workload read every secret in the project, "
            "so removing one secret's environment variable from the service does not remove its access."
        ),
        remediation=(
            "Grant `roles/secretmanager.secretAccessor` with `google_secret_manager_secret_iam_member` on each "
            "secret the service account needs."
        ),
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only google_project_iam_member and google_project_iam_binding resources in .tf files are checked.",
            "Roles must be literal or a literal for_each role set; members must be literal `serviceAccount:` strings.",
            "Human users and groups are not reported, and access inherited from folders or organizations is not inferred.",
        ),
        examples=tuple(
            RuleExample(
                example_id=example_id,
                title=title,
                outcome=outcome,
                files=(ExampleFile.iac("main.tf", source),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=count,
                public=True,
            )
            for example_id, title, outcome, source, count in (
                (
                    "project-secret-accessor",
                    "A service account can read every project secret",
                    ExampleOutcome.MATCH,
                    (
                        'resource "google_project_iam_member" "api" {\n'
                        '  role   = "roles/secretmanager.secretAccessor"\n'
                        '  member = "serviceAccount:${google_service_account.api.email}"\n'
                        "}\n"
                    ),
                    1,
                ),
                (
                    "per-secret-accessor",
                    "A service account reads only the secret it needs",
                    ExampleOutcome.NO_MATCH,
                    (
                        'resource "google_secret_manager_secret_iam_member" "api" {\n'
                        "  secret_id = google_secret_manager_secret.api_key.id\n"
                        '  role      = "roles/secretmanager.secretAccessor"\n'
                        '  member    = "serviceAccount:${google_service_account.api.email}"\n'
                        "}\n"
                    ),
                    0,
                ),
            )
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix.lower() != ".tf" or "secretmanager" not in source:
            return []
        try:
            top = balanced_blocks(source)
        except ValueError:
            return []
        collections = local_collections(top)
        findings: list[Diagnostic] = []
        for block in top:
            if block.type != "resource" or not block.labels or block.labels[0] not in _GRANTS:
                continue
            roles = sorted(grant_roles(block, collections) & _SECRET_ROLES)
            if roles and block.child("condition") is None and _grants_service_account(block):
                findings.append(
                    Diagnostic(
                        path,
                        block.line,
                        block.col,
                        self.code,
                        f"Project IAM grants {', '.join(roles)} to a service account; grant it on each secret "
                        "with google_secret_manager_secret_iam_member",
                    )
                )
        return findings


def _grants_service_account(block: Block) -> bool:
    attribute = block.attribute("member", "members")
    if attribute is None:
        return False
    return any(token.startswith(_SERVICE_ACCOUNT_PREFIX) for token in tokens(attribute.value))
