"""SARJ038: module-scope unscoped suppression blanket — scope it or fix the findings.

A per-line suppression is a claim about one line. A module-scope *unscoped*
blanket is a claim about every line in the file, forever: it switches the whole
checker off for the file, including the rules that do not exist yet. The next
person adds a function to the file and their new violations are pre-silenced by
a decision someone else made months ago, in a comment they will never scroll
past. Nothing in review or CI says a word. This is the file-level-suppression
escape hatch raised in review (`sarj-ai/bulbul#2881`).

A SCOPED suppression is the opposite: naming the codes it silences makes it a
reviewed, legible, bounded decision, and it keeps working exactly as intended
when new rules land. Scoped forms are NEVER flagged by this rule.

Fires on exactly three shapes:

1. Bare `# ruff: noqa` — anywhere in the file, since ruff honours the
   file-level exemption wherever the comment appears. A trailing prose reason
   (`# ruff: noqa — legacy module`) is still unscoped: it names no codes.
2. Standalone `# type: ignore` (mypy) appearing BEFORE the module's first
   statement — that position is what makes it file-level rather than per-line.
3. Standalone `# pyright: ignore` before the module's first statement.

"Standalone" means the comment is the only thing on its line. "Before the first
statement" means above the line of the first token that is not a comment or
layout — a module docstring IS a statement, so a `# type: ignore` under the
docstring is not file-level.

Deliberately NOT flagged:

* every scoped counterpart — `# ruff: noqa: E501`, `# ruff: noqa: E501, F401`,
  `# type: ignore[attr-defined]`, `# pyright: ignore[reportUnusedImport]`;
* trailing per-line suppressions — `x = foo()  # type: ignore`,
  `y = bar()  # pyright: ignore` — these bind to one line by construction, and
  their position in the file is irrelevant;
* a bare per-line `# noqa` with no `ruff:` prefix: it silences one line, not the
  file, and belongs to a different rule;
* other `ruff:` directives that are not `noqa` (`# ruff:ignore[...]`), and
  pyright's configuration comments (`# pyright: strict`);
* shebangs, encoding cookies (`# -*- coding: utf-8 -*-`) and license headers,
  which legitimately precede the first statement.

The rule is token-based rather than AST-based because comments do not survive
`ast.parse`. Malformed input yields no diagnostics rather than an exception.

A file-level blanket that is genuinely justified (vendored code, a generated
module) is suppressed with `# sarj-noqa: SARJ038 — <reason>`, which puts the
reason in the diff where a reviewer sees it.
"""

from __future__ import annotations

import re
import tokenize
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule
from sarj_python_lint.rules._suppression_comments import Comment, scan_comments


if TYPE_CHECKING:
    from pathlib import Path


# Directive heads, spelled as the tools themselves accept them: no space before
# the colon, optional space after. `ruff:` is matched case-insensitively (ruff
# accepts `NOQA`); mypy and pyright only honour their directives in lowercase.
_RUFF_NOQA_RE = re.compile(r"^ruff:\s*noqa(?P<rest>.*)", re.IGNORECASE)
_TYPE_IGNORE_RE = re.compile(r"^type:\s*ignore(?P<rest>.*)")
_PYRIGHT_IGNORE_RE = re.compile(r"^pyright:\s*ignore(?P<rest>.*)")

# What a SCOPED suppression looks like after the directive head: ruff lists its
# codes after a colon, mypy and pyright inside brackets. At least one word
# character is required, since a trailing bare colon names no codes either.
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
    """Module-scope unscoped suppression blanket — scope it to the codes it silences."""

    id: str = "no-file-level-suppression"
    code: str = "SARJ038"
    description: str = (
        "An unscoped file-level suppression (`# ruff: noqa`, `# type: ignore`, "
        "`# pyright: ignore`) switches a whole checker off for the file, "
        "including rules added later — scope it to the codes it silences."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Report every unscoped module-scope suppression blanket in `source`.

        Input that cannot be lexed (unterminated string, bad indentation)
        yields no diagnostics rather than an exception.

        Returns:
            The diagnostics, sorted by (line, col).

        """
        try:
            comments = scan_comments(source)
        except tokenize.TokenError, IndentationError, SyntaxError:
            return []
        diags = [
            Diagnostic(path=path, line=comment.line, col=comment.col, code=self.code, message=message)
            for comment in comments
            if (message := _blanket_message(comment)) is not None
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _blanket_message(comment: Comment) -> str | None:
    """Classify a comment as one of the three unscoped blankets.

    A bare `# ruff: noqa` counts wherever it sits; the mypy and pyright forms
    only count when they stand alone above the module's first statement, since
    anywhere else they are per-line suppressions.

    Returns:
        The diagnostic message, or None when the comment is not a blanket.

    """
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
    """Report whether `body` is `directive` with no code list after it.

    Returns:
        True when the directive matches and names no codes.

    """
    match = directive.match(body)
    if match is None:
        return False
    rest = match["rest"]
    if _WORD_CONTINUATION_RE.match(rest):
        return False
    return not codes.match(rest)
