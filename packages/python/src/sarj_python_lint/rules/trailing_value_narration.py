"""SARJ051 — A trailing comment that spells out a literal already on the line.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_trailing_value_narration.py
"""

from __future__ import annotations

from pathlib import PurePosixPath
import re
import tokenize
from typing import TYPE_CHECKING, ClassVar, override

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
)
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
    id: str = "trailing-value-narration"
    code: str = "SARJ051"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Trailing comment restates a literal value and its unit.",
        rationale="A unit encoded only in a comment can drift from the value and is unavailable to type checking.",
        remediation="Encode the unit in the name or value type, such as timeout_seconds or timedelta.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SUGGESTION,
        limitations=(
            "Detection targets simple numeric assignments with a trailing comment that repeats the number and unit.",
            "Approximate conversions, reasons, references, directives, bracketed values, and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="repeated-duration",
                title="Comment repeats the duration",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("settings.py", "STALE_TIME = 5 * 60 * 1000  # 5 minutes\n"),),
                focus_path=PurePosixPath("settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="comment-explains-policy",
                title="Comment explains a policy",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("settings.py", "BACKOFF = 2 * 60  # doubles per attempt\n"),),
                focus_path=PurePosixPath("settings.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

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
                diags.append(
                    Diagnostic(
                        path=path,
                        line=line,
                        col=col + 1,
                        code=self.code,
                        message=self.description,
                        column_encoding=ColumnEncoding.CODEPOINTS,
                    )
                )
        return diags
