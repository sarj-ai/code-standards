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
from sarj_iac_lint.rules._literal_policy import balanced_blocks


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_iac_lint.terraform import TerraformSession


_INSTANCE_TYPES = frozenset(
    {
        "google_compute_instance",
        "google_compute_instance_template",
        "google_compute_region_instance_template",
        "google_compute_instance_from_template",
    }
)


@final
class NoSensitiveInstanceMetadata(Rule):
    id = "no-sensitive-instance-metadata"
    code = "SARJ226"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="Compute instance metadata should not carry sensitive values.",
        rationale=(
            "Instance metadata is readable by every principal with compute.instances.get, so a password or token "
            "placed there reaches project viewers that cannot read the Secret Manager secret."
        ),
        remediation=(
            "Pass the Secret Manager secret ID in metadata and read the value on the VM with its service account."
        ),
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Only `metadata` attributes of Compute Engine instance and template resources in .tf files are checked; "
                "a value is reported when it references a same-module variable declared `sensitive = true` or a "
                "`secret_data` attribute."
            ),
            "Secrets reached through locals, module outputs, template interpolation or startup scripts are not recognized.",
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
                    "sensitive-variable",
                    "A sensitive password is copied into instance metadata",
                    ExampleOutcome.MATCH,
                    (
                        'variable "db_password" {\n  type      = string\n  sensitive = true\n}\n\n'
                        'resource "google_compute_instance" "vm" {\n'
                        "  metadata = {\n    db-password = var.db_password\n  }\n}\n"
                    ),
                    1,
                ),
                (
                    "secret-id",
                    "The VM receives only the secret ID",
                    ExampleOutcome.NO_MATCH,
                    (
                        'variable "domain" {\n  type = string\n}\n\n'
                        'resource "google_compute_instance" "vm" {\n'
                        '  metadata = {\n    db-password-secret-id = "db-password"\n    domain = var.domain\n  }\n}\n'
                    ),
                    0,
                ),
            )
        ),
    )
    description = documentation.summary

    def __init__(
        self,
        *,
        session: TerraformSession | None = None,  # sarj-noqa: SARJ468 -- Registry requires no-argument factories.
    ) -> None:
        self.session = session

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix.lower() != ".tf" or "metadata" not in source:
            return []
        try:
            top = balanced_blocks(source)
        except ValueError:
            return []
        sensitive = frozenset(
            f"var.{block.labels[0]}"
            for block in (self.session.blocks(path) if self.session is not None else top)
            if block.type == "variable"
            and len(block.labels) == 1
            and (flag := block.attribute("sensitive")) is not None
            and flag.value.strip() == "true"
        )
        return [
            Diagnostic(
                path,
                metadata.line,
                metadata.col,
                self.code,
                "Instance metadata receives a sensitive value; pass the Secret Manager secret ID instead",
            )
            for block in top
            if block.type == "resource"
            and block.labels
            and block.labels[0] in _INSTANCE_TYPES
            and (metadata := block.attribute("metadata")) is not None
            and any(token in sensitive or token.endswith(".secret_data") for token in tokens(metadata.value))
        ]
