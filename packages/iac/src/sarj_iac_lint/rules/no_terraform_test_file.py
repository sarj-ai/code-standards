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


@final
class NoTerraformTestFile(Rule):
    id = "no-terraform-test-file"
    code = "SARJ206"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Committed Terraform test file couples validation to IaC source configuration.",
        rationale=(
            "Terraform test files are repository-side configuration oracles that can validate implementation shape "
            "instead of a reviewed plan, provider state, or deployed behavior."
        ),
        remediation=(
            "Remove the .tftest.hcl or .tftest.json file and validate a real rendered plan, provider API, or runtime contract."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The linter evaluates files supplied by the caller; the repository runner must pass every tracked IaC file.",
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
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        del source
        if not path.name.casefold().endswith(_BANNED_SUFFIXES):
            return []
        return [
            Diagnostic(
                path=path,
                line=1,
                col=1,
                code=self.code,
                message=(
                    "Terraform test files are prohibited; validate a rendered plan, provider state, or runtime behavior instead."
                ),
                suppressible=False,
                baselineable=False,
            )
        ]
