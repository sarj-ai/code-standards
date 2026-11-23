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
from sarj_python_lint.rules.no_test_comments import owns_test_comments


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MAX_COMMENT_LINES = 2
_MAX_COMMENT_WORDS = 40
_DIRECTIVE = re.compile(
    r"^(?:noqa\b|sarj-noqa\b|type:|pragma:|(?:based)?pyright:|mypy:|fmt:|isort:|ruff:|pylint:|flake8:|codespell:|nosec\b|nosemgrep\b|coding[:=]|-\*-)",
    re.IGNORECASE,
)

_LEGAL_NOTICE = re.compile(
    r"^\s*(?:copyright\b|spdx-license-identifier:|permission is hereby granted\b|licensed under\b|all rights reserved\b)",
    re.IGNORECASE,
)
_PRODUCTION_MESSAGE = "Delete this comment; express its meaning in names, types or code."
_TEST_PARAGRAPH_MESSAGE = (
    "Keep a necessary constraint within two comment lines and 40 words; move longer prose to documentation."
)
_TEST_INLINE_MESSAGE = "Keep a necessary inline constraint within 40 words; move longer prose to documentation."


@final
class ExcessiveCommentary(Rule):
    id = "excessive-commentary"
    code = "SARJ434"
    documentation = RuleDocumentation(
        summary="Production code carries no ordinary comments; express intent in names, types and code.",
        rationale=(
            "Comments drift from the code they describe. Names, types, structure and executable contracts keep the "
            "explanation checked; documentation owns longer context."
        ),
        remediation=(
            "Delete the comment. Move its meaning into a name, type, helper or assertion, or into documentation. "
            "Preserve machine directives, their suppression descriptions and legal notices."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Safe fixes remove only a paragraph accepted by the shared ordered-narration proof: flat zero-argument direct calls, single-name call assignments and a terminal call return, or the exact initializer/accumulator-calls/return shape. Every line must repeat its corresponding action name; constraints, directives, qualifiers and extra statements remain protected. Each removed comment leaves its original blank line.",
            "Contiguous standalone implementation comment blocks with at least two non-empty lines and 12 words are inspected.",
            "An error requires each line to exactly repeat its corresponding direct zero-argument call identifier in the same order. Supported owners contain only those flat calls, single-name call assignments and call returns, or the exact accumulation shape.",
            "Guards, loops, branches, additional statements, intervening comments, arguments, qualified calls, quoted text, novel words and meaning-bearing qualifiers cause abstention. Arbitrary prose is not inferred to be redundant from its length.",
            "Outside test sources, every nonempty standalone comment paragraph and inline comment is reported, including concise hidden constraints and tracked TODO notes. Test sources owned by no-test-comments keep only the two-line, 40-word paragraph and 40-word inline budget here. These findings are review-only; safe fixes still require the separate ordered-narration proof.",
            "Generated files, validated PEP 723 metadata, shebangs, encoding cookies, legal notices and docstrings are excluded. A comment that starts with a noqa, sarj-noqa, type, pragma, pyright, basedpyright, mypy, fmt, isort, ruff, pylint, flake8, codespell, nosec or nosemgrep directive is exempt together with its trailing suppression description. A directive on one line does not exempt adjacent ordinary prose, and blank lines do not split an otherwise uninterrupted paragraph.",
        ),
        examples=(
            RuleExample(
                example_id="activation-narration",
                scenario="ordered-narration",
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
            ),
            RuleExample(
                example_id="constraint-comment",
                title="A concise constraint comment still restates what the code should name",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        "def record(pool):\n"
                        "    # Settle the row before cancellation can close the pool.\n"
                        "    shield(insert_row(pool))\n",
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="named-constraint",
                title="The name carries the constraint",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        "def record(pool):\n    shield(insert_row_before_pool_closes(pool))\n",
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="described-suppression",
                title="A directive keeps its required suppression description",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="described-suppression",
                files=(
                    ExampleFile.python(
                        "app.py",
                        "value = vendor.value  # pyright: ignore[reportAttributeAccessIssue] -- vendor 2.1 stubs omit value\n",
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
    budgeted = owns_test_comments(context)
    comments, _ = standalone_comments(context.source)
    metadata = script_metadata_lines(context.source, comments)
    ordinary = [item for item in comments if item.line not in metadata and not _machine_directive(item)]
    return [
        Diagnostic(
            context.path,
            paragraph[0].line,
            paragraph[0].column + 1,
            "SARJ434",
            _TEST_PARAGRAPH_MESSAGE if budgeted else _PRODUCTION_MESSAGE,
            severity=Severity.ERROR,
            column_encoding=ColumnEncoding.CODEPOINTS,
        )
        for paragraph in _paragraphs(ordinary, context.source.splitlines())
        if _reported_paragraph(paragraph, budgeted=budgeted)
        and not any(paragraph[0].line <= finding.line <= paragraph[-1].line for finding in existing)
    ] + _inline_findings(context, budgeted=budgeted)


def _inline_findings(context: PythonFileContext, *, budgeted: bool) -> list[Diagnostic]:
    return [
        Diagnostic(
            context.path,
            comment.line,
            comment.column + 1,
            "SARJ434",
            _TEST_INLINE_MESSAGE if budgeted else _PRODUCTION_MESSAGE,
            severity=Severity.ERROR,
            column_encoding=ColumnEncoding.CODEPOINTS,
        )
        for comment in trailing_comments(context.source)
        if comment.body
        and (not budgeted or len(comment.body.split()) > _MAX_COMMENT_WORDS)
        and not _machine_directive(comment)
        and not _LEGAL_NOTICE.match(comment.body)
    ]


def _paragraphs(comments: list[PositionedComment], lines: list[str]) -> list[list[PositionedComment]]:
    paragraphs: list[list[PositionedComment]] = []
    for comment in comments:
        if paragraphs and not any(line.strip() for line in lines[paragraphs[-1][-1].line : comment.line - 1]):
            paragraphs[-1].append(comment)
        else:
            paragraphs.append([comment])
    return paragraphs


def _reported_paragraph(paragraph: list[PositionedComment], *, budgeted: bool) -> bool:
    text = "\n".join(item.body for item in paragraph)
    return (
        bool(text.strip())
        and not _LEGAL_NOTICE.match(text)
        and (
            not budgeted
            or len([item for item in paragraph if item.body.strip()]) > _MAX_COMMENT_LINES
            or len(text.split()) > _MAX_COMMENT_WORDS
        )
    )


def _machine_directive(comment: PositionedComment) -> bool:
    return bool(_DIRECTIVE.match(comment.body)) or (comment.line == 1 and comment.body.startswith(("!/", "! /")))
