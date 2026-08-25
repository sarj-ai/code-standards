from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

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


_BANNED_SUFFIXES = (".tftest.hcl", ".tftest.json")
_BANNED_NAMES = frozenset({"verify-environment-boundary.test.mjs", "verify-dev-apply-plan.jq"})


@final
class NoTerraformTestFile(Rule):
    id = "no-terraform-test-file"
    code = "SARJ206"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Committed Terraform test or prohibited named IaC verifier couples validation to implementation shape.",
        rationale=(
            "Terraform test files and the named environment-plan verifiers become repository-side configuration oracles "
            "that encode transient resource addresses and implementation shape instead of durable provider or runtime contracts."
        ),
        remediation=(
            "Remove the file and validate provider state, a durable runtime contract, or a shared policy boundary."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The linter evaluates files supplied by the caller; the repository runner must pass every tracked IaC file.",
            "The verifier-file policy is intentionally limited to two exact case-insensitive basenames.",
            "This categorical repository policy intentionally cannot be suppressed or baselined.",
        ),
        examples=(
            RuleExample(
                example_id="terraform-test-file",
                title="Do not commit Terraform test files",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.iac("tests/routing.tftest.hcl", 'run "routing" {}\n'),),
                focus_path=PurePosixPath("tests/routing.tftest.hcl"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="terraform-module-source",
                title="Regular Terraform configuration remains eligible for semantic rules",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.iac("main.tf", 'resource "example_service" "main" {}\n'),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="bespoke-environment-plan-verifier",
                title="Do not commit a bespoke environment plan verifier",
                outcome=ExampleOutcome.MATCH,
                scenario="plan-verifier",
                files=(ExampleFile.iac("iac/scripts/verify-dev-apply-plan.jq", ".resource_changes\n"),),
                focus_path=PurePosixPath("iac/scripts/verify-dev-apply-plan.jq"),
                expected_count=1,
                public=False,
            ),
            RuleExample(
                example_id="runtime-health-check",
                title="Runtime health checks remain eligible",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="plan-verifier",
                files=(ExampleFile.iac("iac/scripts/check-runtime-health.mjs", "await fetch(endpoint);\n"),),
                focus_path=PurePosixPath("iac/scripts/check-runtime-health.mjs"),
                expected_count=0,
                public=False,
            ),
            RuleExample(
                example_id="environment-boundary-source-test",
                title="Do not commit the environment-boundary source test",
                outcome=ExampleOutcome.MATCH,
                scenario="source-verifier",
                files=(
                    ExampleFile.iac(
                        "iac/scripts/verify-environment-boundary.test.mjs",
                        "assert.match(source, /allowed_change_addresses/);\n",
                    ),
                ),
                focus_path=PurePosixPath("iac/scripts/verify-environment-boundary.test.mjs"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="environment-boundary-runtime-check",
                title="Runtime boundary checks remain eligible",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="source-verifier",
                files=(
                    ExampleFile.iac(
                        "iac/scripts/verify-environment-boundary.mjs",
                        "export function verifyPlan(plan) { return plan.resource_changes; }\n",
                    ),
                ),
                focus_path=PurePosixPath("iac/scripts/verify-environment-boundary.mjs"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        del source
        name = path.name.casefold()
        if not name.endswith(_BANNED_SUFFIXES) and name not in _BANNED_NAMES:
            return []
        return [
            Diagnostic(
                path=path,
                line=1,
                col=1,
                code=self.code,
                message=(
                    "Terraform tests and bespoke environment-plan verifiers are prohibited; validate provider state, "
                    "a durable runtime contract, or a shared policy boundary instead."
                ),
                suppressible=False,
                baselineable=False,
            )
        ]
