from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
from sarj_iac_lint.rules._literal_policy import balanced_blocks


if TYPE_CHECKING:
    from pathlib import Path


@final
class NoManagedServiceAccountKey(Rule):
    id = "no-managed-service-account-key"
    code = "SARJ211"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Disallow Terraform-managed Google service-account keys.",
        rationale="Managed private keys persist in Terraform state and create long-lived credentials.",
        remediation="Use workload identity federation or service-account impersonation instead of creating a key.",
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only google_service_account_key resource blocks in .tf files are checked; data sources are allowed.",
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
                    "managed-key",
                    "A managed key creates persistent credentials",
                    ExampleOutcome.MATCH,
                    'resource "google_service_account_key" "app" { service_account_id = "app" }\n',
                    1,
                ),
                (
                    "service-account",
                    "A service account needs no managed key",
                    ExampleOutcome.NO_MATCH,
                    'resource "google_service_account" "app" { account_id = "app" }\n',
                    0,
                ),
            )
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix.lower() != ".tf":
            return []
        try:
            top = balanced_blocks(source)
        except ValueError:
            return []
        return [
            Diagnostic(
                path,
                block.line,
                block.col,
                self.code,
                "Terraform creates a long-lived service-account key; use workload identity or impersonation",
            )
            for block in top
            if block.type == "resource" and block.labels and block.labels[0] == "google_service_account_key"
        ]
