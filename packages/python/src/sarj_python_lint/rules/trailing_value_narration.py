"""SARJ051: a trailing comment that spells out a literal already on the line.

    STALE_TIME = 5 * 60 * 1000  # 5 minutes

The comment adds one thing — the unit — and the line already carries every
number in it. Put the unit in the *name* (`STALE_TIME_MS`, or a `timedelta`)
and the fact travels with the value: it survives a copy-paste, it is visible at
every call site, and it cannot drift when someone edits the arithmetic and
forgets the comment. That drift is the whole risk; a wrong unit comment is worse
than none.

**The test is deliberately narrow.** Every one of these must hold:

- the code before the comment contains at least one numeric literal;
- the comment contains at least one number, and EVERY number it contains
  appears verbatim in that code (`# 5 minutes` over `5 * 60 * 1000` qualifies;
  `# about a working week` over `60 * 60 * 24 * 5` does not, and neither does
  `# ~3.5 days` over `300000` — a conversion the reader cannot do in their
  head is exactly the comment worth keeping);
- the comment names a **unit**. This is the rule's whole premise — "the comment
  adds one thing, the unit" — and without it the identifier arm alone let
  through comments that state a domain fact rather than a unit
  (`_OUNCE_TO_G = _POUND_TO_G / 16  # 16 ounces to a pound`, `# 0 -> 0` over a
  parametrize case, `# Invalid day (32)`). Those are not restatements of a
  value; they are why the constant has that value, and they stay.
- every non-numeric word is either a unit word or already an identifier on the
  line;
- the comment is **not inside a bracketed expression**. The remedy this rule
  prescribes is *put the unit in the name*, which presupposes a name to put it
  in. A comment on a dict entry, a call kwarg or a tuple element has none — a
  pytest fixture's `"value": 60,  # 60 seconds`, a third-party kwarg's
  `cookTime=60,  # 60 seconds`, `t.valve_position = 25  # 25%`. There the
  comment is the *only* carrier of the unit and deleting it loses the fact.

A comment carrying a ticket or URL is exempt (protected-class signal S1).

**Measured.** 19 hits across the maintained repos, 19 of 19 true positives — one
first-party dashboard's analytics hook alone holds 14
`staleTime` lines, and an internal Workers repo's config module carries
`export const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 90;  // 90 days`. TanStack
Query adds 24 more of the same `gcTime: 1000 * 60 * 60 * 24, // 24 hours` idiom.

Every one of those is TypeScript. **This Python rule ships with ZERO hits across
two first-party repos, pydantic, trio and attrs** — it is a ratchet against the shape
appearing, not a cleanup of one that has, and it is listed here rather than
quietly dropped so the two languages cannot diverge on the same judgement.

The last two guards were added by a sweep over home-assistant (18,069 files) and
airflow (7,656), which produced 22 hits the original predicate could not tell
apart. Every one was read: **8 true positives, 14 false** (64%), and every false
positive was one of the two shapes above — 10 inside a bracketed expression, 4
with no unit word in the comment at all. With both guards the same corpus yields
**8 hits, 8 true positives, 0 false**.

Suppress an intentional case with `# sarj-noqa: SARJ051 — <reason>`.
"""

from __future__ import annotations

import re
import tokenize
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule
from sarj_python_lint.rules._comments import (
    code_tokens,
    has_external_reference,
    nested_comment_lines,
    stem,
    trailing_comments,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


# A number that is not part of an identifier or a dotted attribute path.
_NUMBER_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])")
_WORD_RE = re.compile(r"[A-Za-z]+(?:'[a-z]+)?|\d+(?:\.\d+)?")

# Words that name the unit rather than the quantity — the one thing the code
# does not say, and the reason the fix is a *name*, not a deletion.
_UNIT_WORDS = frozenset(
    {
        "bytes",
        "characters",
        "chars",
        "day",
        "days",
        "gb",
        "hour",
        "hours",
        "hr",
        "hrs",
        "hz",
        "items",
        "k",
        "kb",
        "khz",
        "m",
        "mb",
        "milliseconds",
        "min",
        "mins",
        "minute",
        "minutes",
        "ms",
        "pct",
        "percent",
        "px",
        "retries",
        "rows",
        "s",
        "sec",
        "second",
        "seconds",
        "secs",
        "times",
        "tokens",
    }
)

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "we",
        "with",
    }
)

_DIRECTIVE_RE = re.compile(
    r"^\s*(?:todo|fixme|hack\b|xxx|noqa|sarj-noqa|type:|pragma|pyright|mypy|fmt:|isort|ruff|"
    r"pylint|flake8|nosec|nosemgrep)",
    re.IGNORECASE,
)


def _narrates_value(body: str, code: str) -> bool:
    if not body or _DIRECTIVE_RE.match(body) or has_external_reference(body):
        return False
    code_numbers = {match.group(0) for match in _NUMBER_RE.finditer(code)}
    if not code_numbers:
        return False
    words = [match.group(0).lower() for match in _WORD_RE.finditer(body)]
    if not words:
        return False
    comment_numbers = {match.group(0) for match in _NUMBER_RE.finditer(body)}
    if not comment_numbers or not comment_numbers <= code_numbers:
        return False
    if not any(word in _UNIT_WORDS for word in words):
        return False
    identifiers = code_tokens(code)
    identifier_stems = {stem(token) for token in identifiers}
    for word in words:
        if word in _STOPWORDS or word in _UNIT_WORDS or word in comment_numbers:
            continue
        if word in identifiers or stem(word) in identifier_stems:
            continue
        return False
    return True


class TrailingValueNarration(Rule):
    """A trailing comment whose every word and number is already on the line."""

    id: str = "trailing-value-narration"
    code: str = "SARJ051"
    description: str = (
        "Trailing comment restates the literal on this line — put the unit in "
        "the name (STALE_TIME_MS, or a timedelta) so it cannot drift."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        try:
            trailing = trailing_comments(source)
            nested = nested_comment_lines(source)
        except tokenize.TokenError, IndentationError, SyntaxError:
            return []
        lines = source.splitlines()
        diags: list[Diagnostic] = []
        for line, col, body in trailing:
            if line > len(lines) or line in nested:
                continue
            if _narrates_value(body, lines[line - 1][:col]):
                diags.append(Diagnostic(path=path, line=line, col=col + 1, code=self.code, message=self.description))
        return diags
