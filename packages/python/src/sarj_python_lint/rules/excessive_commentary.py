from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    ColumnEncoding,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._comment_narration import CommentNarration
from sarj_python_lint.rules._comments import (
    PositionedComment,
    script_metadata_lines,
    standalone_comments,
    trailing_comments,
)
from sarj_python_lint.rules._prose_budget import groups


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MAX_COMMENT_LINES = 2
_MAX_COMMENT_WORDS = 40
_DIRECTIVE = re.compile(
    r"^(?:noqa\b|sarj-noqa\b|type:|pragma:|pyright:|mypy:|fmt:|isort:|ruff:|pylint:|flake8:|nosec\b|nosemgrep\b|coding[:=]|-\*-)",
    re.IGNORECASE,
)

_LEGAL_NOTICE = re.compile(
    r"^\s*(?:copyright\b|spdx-license-identifier:|permission is hereby granted\b|licensed under\b|all rights reserved\b)",
    re.IGNORECASE,
)


@final
class ExcessiveCommentary(Rule):
    id = "excessive-commentary"
    code = "SARJ434"
    documentation = RuleDocumentation(
        summary="Keep necessary comments within two lines and 40 words; delete redundant narration.",
        rationale=(
            "Names, types and executable contracts should explain behavior. Rare hidden constraints need concise local "
            "comments; paragraphs of explanation belong in documentation."
        ),
        remediation=(
            "Delete duplicate narration. Keep a necessary hidden constraint within two lines and 40 words, or use an "
            "exact-code justified exception for a required longer contract. Preserve machine directives and legal notices."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Safe fixes remove only a paragraph accepted by the shared ordered-narration proof: flat zero-argument direct calls, single-name call assignments and a terminal call return, or the exact initializer/accumulator-calls/return shape. Every line must repeat its corresponding action name; constraints, directives, qualifiers and extra statements remain protected. Each removed comment leaves its original blank line.",
            "Contiguous standalone implementation comment blocks with at least two non-empty lines and 12 words are inspected.",
            "An error requires each line to exactly repeat its corresponding direct zero-argument call identifier in the same order. Supported owners contain only those flat calls, single-name call assignments and call returns, or the exact accumulation shape.",
            "Guards, loops, branches, additional statements, intervening comments, arguments, qualified calls, quoted text, novel words and meaning-bearing qualifiers cause abstention. Arbitrary prose is not inferred to be redundant from its length.",
            "The explicit source-prose policy rejects standalone comment paragraphs above two nonempty lines or 40 words, even when technically meaningful. Budget findings are review-only; safe fixes still require the separate ordered-narration proof.",
            "Generated files, validated PEP 723 metadata, machine directives, legal notices and docstrings are excluded from the paragraph budget. Inline comments retain the word budget. A directive on one line does not exempt adjacent ordinary prose, and blank lines do not split an otherwise uninterrupted paragraph.",
        ),
        examples=(
            RuleExample(
                example_id="activation-narration",
                title="A paragraph exactly repeats two flat action names",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        "def activate():\n"
                        "    # Load current account profile activation settings\n"
                        "    # Build current account profile activation response\n"
                        "    load_current_account_profile_activation_settings()\n"
                        "    return build_current_account_profile_activation_response()\n",
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="activation-rationale",
                title="A concise necessary constraint remains local",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        "def activation_reasons():\n"
                        "    # Returns all the reasons rather than the first failure.\n"
                        "    # That avoids discovering one problem per round trip.\n"
                        "    reasons = []\n"
                        "    reasons.extend(integration_reasons())\n"
                        "    reasons.extend(endpoint_reasons())\n"
                        "    return reasons\n",
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="durable-constraint",
                title="A concrete compatibility constraint remains local",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="durable-constraint",
                files=(
                    ExampleFile.python(
                        "app.py",
                        "# Legacy clients send `execution_phase` until API-812 is retired.\n"
                        "# Keep the adapter at this boundary so internal models stay camelCase.\n"
                        'phase = payload["execution_phase"]\n',
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=0,
            ),
            RuleExample(
                example_id="safe-autofix-subset",
                title="Exact authored words have a convergent comment fix",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "def reasons():\n    # Collect active account profile activation rejection reasons\n    # Collect current endpoint profile activation rejection reasons\n    # Collect current integration profile activation rejection reasons\n    # Collect current action profile activation rejection reasons\n    values = []\n    values.extend(collect_active_account_profile_activation_rejection_reasons())\n    values.extend(collect_current_endpoint_profile_activation_rejection_reasons())\n    values.extend(collect_current_integration_profile_activation_rejection_reasons())\n    values.extend(collect_current_action_profile_activation_rejection_reasons())\n    return values\n",
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/service.py",
                        "def reasons():\n\n\n\n\n    values = []\n    values.extend(collect_active_account_profile_activation_rejection_reasons())\n    values.extend(collect_current_endpoint_profile_activation_rejection_reasons())\n    values.extend(collect_current_integration_profile_activation_rejection_reasons())\n    values.extend(collect_current_action_profile_activation_rejection_reasons())\n    return values\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated:
            return []
        narration = CommentNarration(context)
        findings: list[Diagnostic] = []
        for group in groups(context.path, context.source, tree=context.tree):
            if narration.match(group) is None:
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    group.line,
                    group.col,
                    self.code,
                    self.description,
                    severity=Severity.ERROR,
                    column_encoding=group.column_encoding,
                )
            )
        return [*findings, *_budget_findings(context, findings)]


def _budget_findings(context: PythonFileContext, existing: list[Diagnostic]) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    comments, _ = standalone_comments(context.source)
    metadata = script_metadata_lines(context.source, comments)
    ordinary = [item for item in comments if item.line not in metadata and not _machine_directive(item)]
    for paragraph in _paragraphs(ordinary, context.source.splitlines()):
        if not _long_paragraph(paragraph):
            continue
        if any(paragraph[0].line <= finding.line <= paragraph[-1].line for finding in existing):
            continue
        findings.append(
            Diagnostic(
                context.path,
                paragraph[0].line,
                paragraph[0].column + 1,
                "SARJ434",
                "Keep a necessary constraint within two comment lines and 40 words; move longer prose to documentation.",
                severity=Severity.ERROR,
                column_encoding=ColumnEncoding.CODEPOINTS,
            )
        )
    for comment in trailing_comments(context.source):
        if (
            len(comment.body.split()) <= _MAX_COMMENT_WORDS
            or _machine_directive(comment)
            or _LEGAL_NOTICE.match(comment.body)
        ):
            continue
        findings.append(
            Diagnostic(
                context.path,
                comment.line,
                comment.column + 1,
                "SARJ434",
                "Keep a necessary inline constraint within 40 words; move longer prose to documentation.",
                severity=Severity.ERROR,
                column_encoding=ColumnEncoding.CODEPOINTS,
            )
        )
    return findings


def _paragraphs(comments: list[PositionedComment], lines: list[str]) -> list[list[PositionedComment]]:
    paragraphs: list[list[PositionedComment]] = []
    for comment in comments:
        if paragraphs and not any(line.strip() for line in lines[paragraphs[-1][-1].line : comment.line - 1]):
            paragraphs[-1].append(comment)
        else:
            paragraphs.append([comment])
    return paragraphs


def _long_paragraph(paragraph: list[PositionedComment]) -> bool:
    text = "\n".join(item.body for item in paragraph)
    return not _LEGAL_NOTICE.match(text) and (
        len([item for item in paragraph if item.body.strip()]) > _MAX_COMMENT_LINES
        or len(text.split()) > _MAX_COMMENT_WORDS
    )


def _machine_directive(comment: PositionedComment) -> bool:
    return bool(_DIRECTIVE.match(comment.body)) or (comment.line == 1 and comment.body.startswith(("!/", "! /")))
