from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import comma_parts, literal_string, strip_outer_parentheses, tokens
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
_SERVICE_ACCOUNT_PREFIX = "serviceAccount:"
_MAX_COLLECTION_CONVERSIONS = 32


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
            "Roles must resolve to static strings or literal for_each role sets through same-file locals and joins; members must directly declare `serviceAccount:` strings or templates, individually or in a list, including up to 32 nested `toset` and `tolist` conversions.",
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
                scenario=(
                    "static-role-principal"
                    if example_id in {"joined-project-secret-accessor", "transformed-human-member"}
                    else "primary"
                ),
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
                    "joined-project-secret-accessor",
                    "A static role expression still grants project-wide access",
                    ExampleOutcome.MATCH,
                    (
                        'resource "google_project_iam_member" "api" {\n'
                        '  role = join("", ["roles/secret", "manager.secretAccessor"])\n'
                        '  member = "serviceAccount:worker@example.com"\n}\n'
                    ),
                    1,
                ),
                (
                    "transformed-human-member",
                    "A source string does not prove the resulting identity",
                    ExampleOutcome.NO_MATCH,
                    (
                        'resource "google_project_iam_member" "api" {\n'
                        '  role = join("", ["roles/secret", "manager.secretAccessor"])\n'
                        '  member = replace("serviceAccount:eng@example.com", "serviceAccount:", "group:")\n}\n'
                    ),
                    0,
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
        if path.suffix.lower() != ".tf" or "role" not in source:
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
                        severity=DefaultLevel.WARNING,
                    )
                )
        return findings


def _grants_service_account(block: Block) -> bool:
    attribute = block.attribute("member", "members")
    if attribute is None:
        return False
    parts = strip_outer_parentheses(tokens(attribute.value))
    if attribute.name == "member":
        return _service_account_literal(parts)
    conversions = 0
    while parts[:1] in {("toset",), ("tolist",)}:
        if conversions >= _MAX_COLLECTION_CONVERSIONS:
            return False
        conversions += 1
        arguments = strip_outer_parentheses(parts[1:])
        if arguments == parts[1:] or len(comma_parts(arguments)) != 1:
            return False
        parts = strip_outer_parentheses(arguments)
    if parts[:1] != ("[",) or parts[-1:] != ("]",):
        return False
    return any(_service_account_literal(element) for element in comma_parts(parts[1:-1]))


def _service_account_literal(parts: tuple[str, ...]) -> bool:
    parts = strip_outer_parentheses(parts)
    if len(parts) != 1:
        return False
    raw = parts[0]
    value = literal_string(raw)
    if value is None and raw.startswith('"'):
        prefix = raw.split("${", 1)[0].split("%{", 1)[0]
        value = literal_string(f'{prefix}"')
    return value is not None and value.startswith(_SERVICE_ACCOUNT_PREFIX)
