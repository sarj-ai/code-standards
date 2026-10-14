from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import literal_string
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
    from collections.abc import Iterator
    from pathlib import Path

    from sarj_iac_lint._hcl import Block


_SECRET_NAME = re.compile(r"^(?:[A-Z0-9]+_)*(?:SECRET|TOKEN|PASSWORD|API_KEY|PRIVATE_KEY)$")


@final
class NoPlaintextSecretEnv(Rule):
    id = "no-plaintext-secret-env"
    code = "SARJ214"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="A secret-named container environment variable should come from a secret reference, not a plain value.",
        rationale=(
            "A plain `value` copies the secret into Terraform state, the plan output and the service revision, where "
            "anyone who can read them sees it, and rotating it needs a redeploy."
        ),
        remediation=(
            "Store the secret in Secret Manager and reference it with `value_source { secret_key_ref { ... } }` or "
            "`value_from { secret_key_ref { ... } }`."
        ),
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only `env` blocks inside Terraform resources in .tf files are checked.",
            (
                "The literal name must end in SECRET, TOKEN, PASSWORD, API_KEY or PRIVATE_KEY; other secrets, such as a "
                "password interpolated into a connection string, are not recognized."
            ),
            "Empty literal values are not reported.",
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
                    "plain-api-key",
                    "An API key is injected as a plain value",
                    ExampleOutcome.MATCH,
                    (
                        'resource "google_cloud_run_v2_service" "api" {\n  template {\n    containers {\n'
                        '      env {\n        name  = "API_KEY"\n        value = var.api_key\n      }\n    }\n  }\n}\n'
                    ),
                    1,
                ),
                (
                    "secret-reference",
                    "An API key is read from Secret Manager",
                    ExampleOutcome.NO_MATCH,
                    (
                        'resource "google_cloud_run_v2_service" "api" {\n  template {\n    containers {\n'
                        '      env {\n        name = "API_KEY"\n        value_source {\n          secret_key_ref {\n'
                        "            secret  = google_secret_manager_secret.api_key.secret_id\n"
                        '            version = "latest"\n          }\n        }\n      }\n    }\n  }\n}\n'
                    ),
                    0,
                ),
            )
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix.lower() != ".tf" or "env" not in source:
            return []
        try:
            top = balanced_blocks(source)
        except ValueError:
            return []
        findings: list[Diagnostic] = []
        for resource in top:
            if resource.type != "resource":
                continue
            for env in _env_blocks(resource):
                name_attribute = env.attribute("name")
                value_attribute = env.attribute("value")
                if name_attribute is None or value_attribute is None:
                    continue
                name = literal_string(name_attribute.value.strip())
                if name is None or not _SECRET_NAME.fullmatch(name):
                    continue
                value = literal_string(value_attribute.value.strip())
                if value is not None and not value:
                    continue
                findings.append(
                    Diagnostic(
                        path,
                        value_attribute.line,
                        value_attribute.col,
                        self.code,
                        f"Environment variable {name} receives a plain value; reference a Secret Manager secret "
                        "with value_source or value_from instead",
                    )
                )
        return findings


def _env_blocks(block: Block) -> Iterator[Block]:
    for child in block.blocks:
        if child.type == "env":
            yield child
        yield from _env_blocks(child)
