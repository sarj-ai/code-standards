from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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

_RESOURCE = "resource"
_TERRAFORM_DATA = "terraform_data"
_LIFECYCLE = "lifecycle"
_CONDITION_BLOCKS = frozenset({"postcondition", "precondition"})


@final
class NoTerraformDataCondition(Rule):
    id = "no-terraform-data-condition"
    code = "SARJ210"
    documentation = RuleDocumentation(
        summary="Disallow lifecycle conditions attached to terraform_data guard resources.",
        rationale=(
            "A terraform_data resource created only to reject a plan turns configuration policy into stateful graph "
            "noise. The assertion drifts with today's configuration while obscuring the input, resource, test, or "
            "deployment boundary that owns the invariant."
        ),
        remediation=(
            "Delete the terraform_data guard. Put an input invariant on its variable, a provider invariant on the "
            "owning resource, and environment or rollout policy in tests and deployment review."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only lifecycle precondition and postcondition blocks directly inside terraform_data resources are checked.",
            (
                "Ordinary terraform_data replacement triggers, variable validation, check blocks, and lifecycle "
                "conditions on provider resources remain allowed."
            ),
            "Only .tf files are read; Terraform test files and other HCL dialects are outside this rule.",
        ),
        examples=(
            RuleExample(
                example_id="terraform-data-plan-guard",
                title="Do not model deployment policy as a fake resource",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'resource "terraform_data" "deployment_guard" {\n'
                        "  lifecycle {\n"
                        "    precondition {\n"
                        "      condition     = var.enabled\n"
                        '      error_message = "deployment must be enabled"\n'
                        "    }\n"
                        "  }\n"
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="terraform-data-replacement-trigger",
                title="Keep terraform_data when it models replacement",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'resource "terraform_data" "release" {\n  triggers_replace = [var.release]\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix.lower() != ".tf":
            return []
        try:
            top = blocks(source)
        except ValueError:
            return []
        return [self._diagnostic(path, block) for block in top if _is_guard(block)]

    def _diagnostic(self, path: Path, block: Block) -> Diagnostic:
        name = block.labels[1] if len(block.labels) > 1 else "<unnamed>"
        return Diagnostic(
            path=path,
            line=block.line,
            col=block.col,
            code=self.code,
            message=(
                f"terraform_data.{name} uses a lifecycle condition as a plan guard — delete the fake resource and "
                "enforce the invariant at its owning input, resource, test, or deployment boundary"
            ),
        )


def _is_guard(block: Block) -> bool:
    if block.type != _RESOURCE or not block.labels or block.labels[0] != _TERRAFORM_DATA:
        return False
    lifecycle = block.child(_LIFECYCLE)
    return lifecycle is not None and any(child.type in _CONDITION_BLOCKS for child in lifecycle.blocks)
