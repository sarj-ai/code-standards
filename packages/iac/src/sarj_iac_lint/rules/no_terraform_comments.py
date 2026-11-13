from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import comment_locations, physical_lines
from sarj_iac_lint.architecture import ArchitectureAnnotationError, parse_module_annotation
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


_SUMMARY_LIMIT = 80
_SUMMARY_DIRECTIVE = re.compile(
    r"\b(?:nosemgrep|noqa|nosec|nolint|nosonar|sarj-noqa)\b|\bkics-scan\s+ignore\b|"
    r"generated.*(?:do not edit|don't edit)|(?:do not edit|don't edit).*generated",
    re.IGNORECASE,
)


@final
class NoTerraformComments(Rule):
    id = "no-terraform-comments"
    code = "SARJ216"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Express Terraform intent through names and descriptions, with optional concise module summaries.",
        rationale="Names and descriptions carry executable intent. An optional short entrypoint summary exposes module purpose without a separate catalog.",
        remediation="Use clear names and native descriptions. Opt into module_summaries for one short main.tf header; keep other context in the owning declaration or change review.",
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Core consumers may opt into [iac.no-terraform-comments] module_summaries = true. This permits one plain # summary of at most 80 characters on the first line of main.tf, followed by a blank line. Suppression and generated-file markers are excluded. Terraform validation still owns syntax; no Terraform values or outputs are added.",
            "With that opt-in, # <purpose> @architecture <min_view> <replacement> adds typed data to the same header. The purpose is at most 40 characters; min_view is overview, standard or detailed; replacement is contract, migration, redesign or unknown. Single spaces separate the marker and enum tokens. The packaged module-architecture.v1.schema.json is the authoritative CALM 1.3 decorator profile; Python types are generated from it. Missing metadata stays unassessed, never implicitly contract-replaceable. This is a Sarj profile, not Terraform metadata or C4 levels.",
            "Malformed, misplaced and conflicting annotations are rejected without echoing their contents. No keyed/JSON syntax, duplicate keys or unknown fields are accepted. Overview visibility is cumulative; filtering never removes complete-export facts. Replacement badges express interface/data migration cost, never hot-swap, downtime or Terraform plan safety. Annotation edits can change deployment hashes and require separate live qualification.",
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

    def __init__(self, *, module_summaries: bool = False) -> None:
        self.module_summaries = module_summaries

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix.lower() != ".tf":
            return []
        if self.module_summaries:
            try:
                parse_module_annotation(path, source)
            except ArchitectureAnnotationError as error:
                return [Diagnostic(path, 1, 1, self.code, str(error), suppressible=False, severity=DefaultLevel.ERROR)]
        summary = (1, 1) if self.module_summaries and _module_summary(path, source) else None
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
            if (line, col) != summary
        ]


def _module_summary(path: Path, source: str) -> bool:
    lines = physical_lines(source)
    if path.name != "main.tf" or lines[1:2] != [""] or not lines[0].startswith("# "):
        return False
    text = lines[0][2:]
    return (
        len(lines[0]) <= _SUMMARY_LIMIT
        and bool(text)
        and text[0].isalpha()
        and text == text.strip()
        and _SUMMARY_DIRECTIVE.search(text) is None
        and all(character not in "{}=:#" and character.isprintable() for character in text)
    )
