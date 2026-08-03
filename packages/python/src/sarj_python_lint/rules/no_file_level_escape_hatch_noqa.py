"""SARJ054 — File-level `# ruff: noqa: TID251` — an escape hatch must be per-line.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_file_level_escape_hatch_noqa.py
"""

from __future__ import annotations

import re
import tokenize
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule
from sarj_python_lint.rules._suppression_comments import scan_comments


if TYPE_CHECKING:
    from pathlib import Path


# The codes whose remediation `ruff.strict.toml` spells as an inline, reasoned
ESCAPE_HATCH_CODES = frozenset({"TID251"})

# Matched as ruff accepts a file-level scoped suppression: case-insensitive on
# the directive head, requiring a colon and at least one code (the code-less
# form is SARJ038's).
_RUFF_SCOPED_NOQA_RE = re.compile(
    r"^ruff:\s*noqa\s*:\s*(?P<codes>[A-Za-z][A-Za-z0-9]*(?:\s*,\s*[A-Za-z][A-Za-z0-9]*)*)",
    re.IGNORECASE,
)


@final
class NoFileLevelEscapeHatchNoqa(Rule):
    id: str = "no-file-level-escape-hatch-noqa"
    code: str = "SARJ054"
    description: str = (
        "A file-level `# ruff: noqa` naming an escape-hatch code (TID251) "
        "pre-authorizes every future use in the file — suppress it inline, "
        "one reviewed `# noqa: TID251 — <reason>` per site."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Report every file-level ruff exemption naming an escape-hatch code."""
        try:
            comments = scan_comments(source)
        except tokenize.TokenError, IndentationError, SyntaxError:
            return []
        diags = [
            Diagnostic(
                path=path,
                line=comment.line,
                col=comment.col,
                code=self.code,
                message=_message(hatched),
            )
            for comment in comments
            if (hatched := _hatch_codes(comment.body))
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _hatch_codes(body: str) -> tuple[str, ...]:
    """Extract the escape-hatch codes named by a file-level ruff exemption."""
    match = _RUFF_SCOPED_NOQA_RE.match(body)
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
