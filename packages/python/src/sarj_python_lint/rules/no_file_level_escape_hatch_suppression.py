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


# These selectors require inline, reasoned suppressions rather than file-wide
# escape hatches. Ruff's preview suppression syntax prefers rule names, while
# its legacy noqa syntax accepts the code.
ESCAPE_HATCH_SELECTORS = frozenset({"TID251", "BANNED-API"})

# Matched as ruff accepts a file-level scoped suppression: case-insensitive on
# the directive head, requiring a colon and at least one code (the code-less
# form is Ruff PGH004's).
_RUFF_FILE_SUPPRESSION_RE = re.compile(
    r"^ruff:\s*(?:"
    r"noqa\s*:\s*(?P<noqa>[A-Za-z][A-Za-z0-9]*(?:\s*,\s*[A-Za-z][A-Za-z0-9]*)*)"
    r"|file-ignore\s*\[\s*(?P<file_ignore>[A-Za-z][A-Za-z0-9-]*(?:\s*,\s*[A-Za-z][A-Za-z0-9-]*)*)\s*\]"
    r")",
    re.IGNORECASE,
)


@final
class NoFileLevelEscapeHatchSuppression(Rule):
    id: str = "no-file-level-escape-hatch-suppression"
    code: str = "SARJ054"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="File-level Ruff suppression disables an escape-hatch rule across the entire file.",
        rationale="A file-wide suppression silently authorizes future uses that were never reviewed.",
        remediation="Suppress each intentional use inline with the exact code and a reason.",
        category=RuleCategory.MAINTAINABILITY,
        aliases=("no-file-level-escape-hatch-noqa",),
        limitations=(
            "Detection covers legacy `ruff: noqa: CODE` and modern `ruff: file-ignore[name]` directives naming configured escape-hatch rules.",
            "Inline noqa comments, balanced Ruff disable/enable ranges, and file-level suppressions for mechanical rules are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="file-wide-escape-hatch",
                title="File suppresses every banned API use",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "# ruff: file-ignore[banned-api]\nimport os\n",
                    ),
                ),
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
                        "import os  # noqa: TID251 — vendor SDK boundary\n",
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
    if not comment.standalone:
        return ()
    match = _RUFF_FILE_SUPPRESSION_RE.match(comment.body)
    if match is None:
        return ()
    raw_selectors = match["noqa"] or match["file_ignore"]
    selectors = [selector.strip().upper() for selector in raw_selectors.split(",")]
    return tuple(
        dict.fromkeys(
            "TID251" for selector in selectors if selector in ESCAPE_HATCH_SELECTORS
        )
    )


def _message(codes: tuple[str, ...]) -> str:
    listed = ", ".join(codes)
    return (
        f"file-level Ruff suppression for `{listed}` pre-authorizes every future use in "
        f"this file, including code not written yet — {listed} is an escape "
        f"hatch whose whole value is the per-site reason, so suppress it inline: "
        f"`# noqa: {codes[0]} — <why this boundary needs it>`."
    )
