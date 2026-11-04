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
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "At error level, takes precedence over the narrower comment-cruft and restated-comment rules when selected together for .tf source. Warning-stage adoption preserves existing errors.",
            "Applies to .tf source, including real comments in template interpolations; literal strings, heredoc script text and non-.tf inputs are not comments.",
            "One finding is emitted per comment token, including block comments and tool directives. This rule cannot suppress itself with another comment.",
            "This is an explicit team style policy, not a claim that explanatory comments are a correctness defect. Conditional safe fixes replace empty ordinary line comments and empty block comments on one physical line with spaces, preserving executable tokens and LF/CRLF boundaries. Nonempty comments, directives, template comments, multiline block comments, generated and malformed sources remain manual.",
        ),
        examples=(
            RuleExample(
                example_id="empty-line-comment",
                scenario="empty-line-comment",
                title="Remove an empty Terraform line comment",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.iac("main.tf", "#\nlocals { value = 1 }\n"),),
                fixed_files=(ExampleFile.iac("main.tf", " \nlocals { value = 1 }\n"),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="empty-line-comment-fixed",
                scenario="empty-line-comment",
                title="The executable Terraform remains unchanged",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.iac("main.tf", " \nlocals { value = 1 }\n"),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="empty-inline-comment",
                scenario="empty-inline-comment",
                title="Keep operators separated when removing an empty block comment",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.iac("main.tf", "locals { value = 1/**/+2 }\n"),),
                fixed_files=(ExampleFile.iac("main.tf", "locals { value = 1    +2 }\n"),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="empty-inline-comment-fixed",
                scenario="empty-inline-comment",
                title="Whitespace preserves the original Terraform operators",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.iac("main.tf", "locals { value = 1    +2 }\n"),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
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
