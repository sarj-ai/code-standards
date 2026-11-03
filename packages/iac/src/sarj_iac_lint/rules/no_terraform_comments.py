from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import comment_locations
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
    from pathlib import Path


@final
class NoTerraformComments(Rule):
    id = "no-terraform-comments"
    code = "SARJ216"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Keep Terraform source free of comments; express intent through names and descriptions.",
        rationale="An explicit no-comment policy keeps infrastructure intent in executable names, descriptions and the change review.",
        remediation="Remove the comment. Preserve necessary context in a descriptive name, description attribute or PR explanation; move tool policy into its supported configuration.",
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "At error level, takes precedence over the narrower comment-cruft and restated-comment rules when selected together for .tf source. Warning-stage adoption preserves existing errors.",
            "Applies to .tf source, including real comments in template interpolations; literal strings, heredoc script text and non-.tf inputs are not comments.",
            "One finding is emitted per comment token, including block comments and tool directives. This rule cannot suppress itself with another comment.",
            "This is an explicit team style policy, not a claim that explanatory comments are a correctness defect. Removal is manual because external tools may interpret directives.",
        ),
        examples=(
            RuleExample(
                example_id="commented-intent",
                title="A Terraform comment duplicates executable intent",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac("main.tf", '# Keep this bucket private.\nresource "example_bucket" "private" {}\n'),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="named-intent",
                title="A resource name and description express intent",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'resource "example_bucket" "private" {\n  description = "Private application storage"\n}\n',
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
        return [
            Diagnostic(
                path,
                line,
                col,
                self.code,
                "Terraform comments are prohibited; use clear names, descriptions or the PR.",
                suppressible=False,
                severity=DefaultLevel.ERROR,
            )
            for line, col in comment_locations(source)
        ]
