from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import ParsedDocument, document_result
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


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sarj_iac_lint._hcl import Block


_RESOURCE_LABEL_COUNT = 2


@final
class NoTerraformGuardBlocks(Rule):
    id = "no-terraform-guard-blocks"
    code = "SARJ222"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Ban Terraform validation, precondition, postcondition, and check blocks.",
        rationale=(
            "The team keeps infrastructure declarations concise and owns custom deployment policy in tests and "
            "deployment preflight. Guard blocks add a second policy layer to those declarations. This is an "
            "explicit design policy, not a claim that Terraform conditions are invalid or always redundant."
        ),
        remediation=(
            "Move any required invariant into its owning test or deployment preflight, then remove the guard block. "
            "Preserve Terraform types, provider validation, deletion protection and lifecycle settings. Review the "
            "behavior before removing a guard; no automatic deletion is provided."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Reports variable validation, resource/data/ephemeral lifecycle preconditions and postconditions, output preconditions, and top-level check blocks in .tf files.",
            "Ordinary conditional expressions, count, for_each, provider condition blocks, prevent_destroy and deletion protection are allowed.",
            "Comments, strings, heredoc payloads, provider blocks with similar names and Terraform test assertions are not guard blocks.",
            "Terraform JSON and other HCL dialects are outside this detector. The shared parser can recover guard prefixes in malformed HCL; native Terraform validation remains necessary.",
            "A check block receives one diagnostic even when it contains multiple assertions or nested data sources.",
        ),
        examples=(
            RuleExample(
                example_id="variable-validation",
                title="Move custom input policy out of variable declarations",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'variable "replicas" {\n  type = number\n  validation {\n    condition = var.replicas > 0\n    error_message = "Require a positive replica count."\n  }\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="resource-precondition",
                scenario="resource-lifecycle",
                title="Move resource preconditions to deployment preflight",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'resource "example_service" "app" {\n  lifecycle {\n    precondition {\n      condition = var.ready\n      error_message = "Require readiness."\n    }\n  }\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="data-postcondition",
                scenario="data-lifecycle",
                title="Move data-source postconditions to their owning policy",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'data "example_image" "selected" {\n  lifecycle {\n    postcondition {\n      condition = self.approved\n      error_message = "Require an approved image."\n    }\n  }\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="check-block",
                scenario="deployment-check",
                title="Keep deployment assertions outside infrastructure declarations",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'check "ready" {\n  assert {\n    condition = var.ready\n    error_message = "Require readiness."\n  }\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="ordinary-declaration",
                title="Keep typed declarations and native lifecycle protection",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'variable "replicas" { type = number }\nresource "example_service" "app" {\n  count = var.enabled ? 1 : 0\n  replicas = var.replicas\n  deletion_protection = true\n  lifecycle { prevent_destroy = true }\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="resource-protection",
                scenario="resource-lifecycle",
                title="Keep native resource lifecycle protection",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf", 'resource "example_service" "app" {\n  lifecycle { prevent_destroy = true }\n}\n'
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="data-selection",
                scenario="data-lifecycle",
                title="Read the selected image without an embedded policy block",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.iac("main.tf", 'data "example_image" "selected" { name = var.image }\n'),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="ordinary-output",
                scenario="deployment-check",
                title="Declare an output without a deployment assertion",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.iac("main.tf", 'output "ready" { value = var.ready }\n'),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        documentation = self.documentation
        if documentation is None or documentation.default_level is DefaultLevel.OFF:
            return []
        return [
            Diagnostic(
                path,
                block.line,
                block.col,
                self.code,
                f"Terraform {block.type} guard blocks are prohibited; move required policy to tests or deployment preflight before removing the block.",
                severity=documentation.default_level,
            )
            for block in guard_blocks(path, source)
        ]


def guard_blocks(path: Path, source: str) -> tuple[Block, ...]:
    if path.suffix.lower() != ".tf":
        return ()
    try:
        parsed = document_result(source)
    except ValueError:
        return ()
    if not isinstance(parsed, ParsedDocument):
        return ()
    return tuple(guard for owner in parsed.root.blocks for guard in _owned_guards(owner))


def _owned_guards(owner: Block) -> Iterator[Block]:
    if owner.type == "check" and len(owner.labels) == 1:
        yield owner
        return
    if owner.type in {"variable", "output"} and len(owner.labels) == 1:
        kind = "validation" if owner.type == "variable" else "precondition"
        yield from _unlabelled_children(owner, kind)
        return
    if owner.type in {"resource", "data", "ephemeral"} and len(owner.labels) == _RESOURCE_LABEL_COUNT:
        for lifecycle in _unlabelled_children(owner, "lifecycle"):
            yield from _unlabelled_children(lifecycle, "precondition", "postcondition")


def _unlabelled_children(owner: Block, *kinds: str) -> Iterator[Block]:
    return (child for child in owner.blocks if child.type in kinds and not child.labels)
