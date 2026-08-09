"""SARJ054 — File-level `# ruff: noqa: TID251` — an escape hatch must be per-line.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_file_level_escape_hatch_noqa.py
"""

from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    ColumnEncoding,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)
from sarj_python_lint.rules._suppression_comments import Comment, scan_comments_or_none


if TYPE_CHECKING:
    from pathlib import Path


# These codes require inline, reasoned suppressions rather than file-wide escape hatches.
ESCAPE_HATCH_CODES = frozenset({"TID251"})

# Matched as ruff accepts a file-level scoped suppression: case-insensitive on
# the directive head, requiring a colon and at least one code (the code-less
# form is Ruff PGH004's).
_RUFF_SCOPED_NOQA_RE = re.compile(
    r"^ruff:\s*noqa\s*:\s*(?P<codes>[A-Za-z][A-Za-z0-9]*(?:\s*,\s*[A-Za-z][A-Za-z0-9]*)*)",
    re.IGNORECASE,
)


@final
class NoFileLevelEscapeHatchNoqa(Rule):
    id: str = "no-file-level-escape-hatch-noqa"
    code: str = "SARJ054"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="File-level Ruff noqa suppresses an escape-hatch rule across the entire file.",
        rationale="A file-wide suppression silently authorizes future uses that were never reviewed.",
        remediation="Suppress each intentional use inline with the exact code and a reason.",
        category=RuleCategory.MAINTAINABILITY,
        limitations=(
            "Detection covers file-level Ruff noqa directives naming configured escape-hatch codes.",
            "Inline noqa comments and file-level suppressions for mechanical rules are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="file-wide-escape-hatch",
                title="File suppresses every banned API use",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/service.py", "# ruff: noqa: TID251\nimport os\n"),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="reasoned-inline-suppression",
                title="One use is suppressed with a reason",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from unittest import mock  # noqa: TID251 — vendor SDK boundary\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Report every file-level ruff exemption naming an escape-hatch code."""
        comments = scan_comments_or_none(source)
        if comments is None:
            return []
        diags = [
            Diagnostic(
                path=path,
                line=comment.line,
                col=comment.col,
                code=self.code,
                message=_message(hatched),
                column_encoding=ColumnEncoding.CODEPOINTS,
            )
            for comment in comments
            if (hatched := _hatch_codes(comment))
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _hatch_codes(comment: Comment) -> tuple[str, ...]:
    """Extract the escape-hatch codes named by a file-level ruff exemption."""
    if not comment.standalone:
        return ()
    match = _RUFF_SCOPED_NOQA_RE.match(comment.body)
    if match is None:
        return ()
    codes = [code.strip().upper() for code in match["codes"].split(",")]
    return tuple(code for code in codes if code in ESCAPE_HATCH_CODES)


def _message(codes: tuple[str, ...]) -> str:
    """Render the diagnostic for the escape-hatch codes found on the line."""
    listed = ", ".join(codes)
    return (
        f"file-level `# ruff: noqa: {listed}` pre-authorizes every future use in "
        f"this file, including code not written yet — {listed} is an escape "
        f"hatch whose whole value is the per-site reason, so suppress it inline: "
        f"`# noqa: {codes[0]} — <why this boundary needs it>`."
    )
