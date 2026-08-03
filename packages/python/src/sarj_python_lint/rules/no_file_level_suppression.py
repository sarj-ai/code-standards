"""SARJ038 — Module-scope unscoped suppression blanket — scope it or fix the findings.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_file_level_suppression.py
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule
from sarj_python_lint.rules._suppression_comments import Comment, scan_comments_or_none


if TYPE_CHECKING:
    from pathlib import Path


# Match directive heads using each tool's accepted spelling.
_RUFF_NOQA_RE = re.compile(r"^ruff:\s*noqa(?P<rest>.*)", re.IGNORECASE)
_TYPE_IGNORE_RE = re.compile(r"^type:\s*ignore(?P<rest>.*)")
_PYRIGHT_IGNORE_RE = re.compile(r"^pyright:\s*ignore(?P<rest>.*)")

# Require a scoped rule list after directive heads that support one.
_RUFF_CODES_RE = re.compile(r"^\s*:\s*\w")
_BRACKET_CODES_RE = re.compile(r"^\s*\[\s*\w")

# `type: ignored` / `ruff: noqas` are different words, not the directive.
_WORD_CONTINUATION_RE = re.compile(r"^\w")

_RUFF_MESSAGE = (
    "bare `# ruff: noqa` exempts this entire file from every ruff rule, "
    "including ones added later — scope it (`# ruff: noqa: E501`) or fix the findings."
)
_TYPE_IGNORE_MESSAGE = (
    "file-level `# type: ignore` silences every mypy error in this file, "
    "including ones added later — scope it (`# type: ignore[attr-defined]`) "
    "or fix the findings."
)
_PYRIGHT_IGNORE_MESSAGE = (
    "file-level `# pyright: ignore` silences every pyright diagnostic in this file, "
    "including ones added later — scope it (`# pyright: ignore[reportUnusedImport]`) "
    "or fix the findings."
)


class NoFileLevelSuppression(Rule):
    id: str = "no-file-level-suppression"
    code: str = "SARJ038"
    description: str = (
        "An unscoped file-level suppression (`# ruff: noqa`, `# type: ignore`, "
        "`# pyright: ignore`) switches a whole checker off for the file, "
        "including rules added later — scope it to the codes it silences."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Report every unscoped module-scope suppression blanket in `source`."""
        comments = scan_comments_or_none(source)
        if comments is None:
            return []
        diags = [
            Diagnostic(path=path, line=comment.line, col=comment.col, code=self.code, message=message)
            for comment in comments
            if (message := _blanket_message(comment)) is not None
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _blanket_message(comment: Comment) -> str | None:
    """Classify a comment as one of the three unscoped blankets."""
    if _is_unscoped(comment.body, _RUFF_NOQA_RE, _RUFF_CODES_RE):
        return _RUFF_MESSAGE
    if not (comment.standalone and comment.before_first_statement):
        return None
    if _is_unscoped(comment.body, _TYPE_IGNORE_RE, _BRACKET_CODES_RE):
        return _TYPE_IGNORE_MESSAGE
    if _is_unscoped(comment.body, _PYRIGHT_IGNORE_RE, _BRACKET_CODES_RE):
        return _PYRIGHT_IGNORE_MESSAGE
    return None


def _is_unscoped(body: str, directive: re.Pattern[str], codes: re.Pattern[str]) -> bool:
    """Report whether `body` is `directive` with no code list after it."""
    match = directive.match(body)
    if match is None:
        return False
    rest = match["rest"]
    if _WORD_CONTINUATION_RE.match(rest):
        return False
    return not codes.match(rest)
