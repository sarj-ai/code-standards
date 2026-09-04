from __future__ import annotations

import ast
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
    Severity,
    parse_or_none,
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
_NUMBER_RE = re.compile(
    r"(?<![\w.])(?:0[xob][0-9a-f_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:e[+-]?\d+)?)(?![\d_.])",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z]+(?:'[a-z]+)?|\d[\d_]*(?:\.\d[\d_]*)?")

# Words that name the unit rather than the quantity — the one thing the code
# does not say, and the reason the fix is a *name*, not a deletion.
_UNIT_WORDS = frozenset(
    {
        "bytes",
        "byte",
        "characters",
        "character",
        "chars",
        "day",
        "days",
        "gb",
        "gib",
        "hour",
        "hours",
        "hr",
        "hrs",
        "hz",
        "items",
        "item",
        "k",
        "kb",
        "kib",
        "khz",
        "m",
        "mb",
        "mib",
        "microseconds",
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
        "retry",
        "rows",
        "row",
        "s",
        "sec",
        "second",
        "seconds",
        "secs",
        "times",
        "tokens",
        "token",
        "us",
        "ns",
        "week",
        "weeks",
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


def _narrates_value(body: str, code: str, code_numbers: frozenset[str]) -> bool:
    if not body or _DIRECTIVE_RE.match(body) or has_external_reference(body):
        return False
    if not code_numbers:
        return False
    words = [match.group(0).lower() for match in _WORD_RE.finditer(body)]
    if not words:
        return False
    comment_number_texts = [match.group(0) for match in _NUMBER_RE.finditer(body)]
    if len(comment_number_texts) != 1:
        return False
    comment_number = _number_key(comment_number_texts[0])
    if comment_number is None or comment_number not in code_numbers:
        return False
    if not any(word in _UNIT_WORDS for word in words):
        return False
    identifiers = code_tokens(code)
    identifier_stems = {stem(token) for token in identifiers}
    for word in words:
        if word in _STOPWORDS or word in _UNIT_WORDS or _number_key(word) == comment_number:
            continue
        if word in identifiers or stem(word) in identifier_stems:
            continue
        return False
    return True


class TrailingValueNarration(Rule):
    id: str = "no-trailing-numeric-unit-assignment-comment"
    code: str = "SARJ051"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="A trailing comment redundantly labels a numeric assignment with its value and unit.",
        rationale=(
            "A unit encoded only in a comment can drift; a unit-bearing name makes it machine- and "
            "reviewer-visible, while a duration type can enforce it."
        ),
        remediation=(
            "Encode or reconcile the unit in the assigned name or typed value, such as timeout_ms or "
            "timedelta(minutes=5), then delete the duplicate comment."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SUGGESTION,
        aliases=("trailing-value-narration",),
        limitations=(
            "Detection targets one-line numeric assignments with one simple name or attribute target and a trailing comment that repeats one number and unit.",
            "Calls, returns, loops, assertions, chained or destructured assignments, multi-number comments, approximate conversions, reasons, references, directives, bracketed values, invalid syntax, and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="repeated-numeric-unit",
                title="Comment repeats the duration",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("settings.py", "STALE_TIME = 5 * 60 * 1000  # 5 minutes\n"),),
                focus_path=PurePosixPath("settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="unit-encoded-in-value",
                title="Typed value carries the unit",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "settings.py",
                        "from datetime import timedelta\n\nSTALE_TIME = timedelta(minutes=5)\n",
                    ),
                ),
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
        if not trailing:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        lines = source.splitlines()
        assignments = _numeric_assignments(tree)
        diags: list[Diagnostic] = []
        for line, col, body in trailing:
            if line > len(lines) or line in nested:
                continue
            if (numbers := assignments.get(line)) is not None and _narrates_value(body, lines[line - 1][:col], numbers):
                diags.append(
                    Diagnostic(
                        path=path,
                        line=line,
                        col=col + 1,
                        code=self.code,
                        message=(
                            f"Trailing numeric-unit label {body.strip()!r} can drift; encode or reconcile the "
                            "unit in the assigned name or value type, then remove the comment."
                        ),
                        severity=Severity.WARNING,
                        column_encoding=ColumnEncoding.CODEPOINTS,
                    )
                )
        return diags


def _numeric_assignments(tree: ast.AST) -> dict[int, frozenset[str]]:
    statements_per_line: dict[int, int] = {}
    candidates: dict[int, list[frozenset[str]]] = {}
    for statement in ast.walk(tree):
        if not isinstance(statement, ast.stmt):
            continue
        statements_per_line[statement.lineno] = statements_per_line.get(statement.lineno, 0) + 1
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)) or statement.end_lineno != statement.lineno:
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        if len(targets) != 1 or not isinstance(targets[0], (ast.Name, ast.Attribute)):
            continue
        value = statement.value
        if value is None or (numbers := _numeric_expression_numbers(value)) is None or not numbers:
            continue
        candidates.setdefault(statement.lineno, []).append(numbers)
    return {
        line: values[0]
        for line, values in candidates.items()
        if len(values) == 1 and statements_per_line.get(line) == 1
    }


def _numeric_expression_numbers(node: ast.expr) -> frozenset[str] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        key = _number_key(node.value)
        return frozenset() if key is None else frozenset({key})
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _numeric_expression_numbers(node.operand)
    if isinstance(node, ast.BinOp) and isinstance(
        node.op,
        (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow),
    ):
        left = _numeric_expression_numbers(node.left)
        right = _numeric_expression_numbers(node.right)
        return None if left is None or right is None else left | right
    return None


def _number_key(value: str | float) -> str | None:
    parsed: object = value
    if isinstance(value, str):
        normalized = value.replace("_", "")
        try:
            parsed = float(normalized) if "." in normalized or "e" in normalized.lower() else int(normalized, 0)
        except ValueError:
            return None
    if isinstance(parsed, bool) or not isinstance(parsed, (int, float)):
        return None
    if isinstance(parsed, float) and parsed.is_integer():
        return str(int(parsed))
    return str(parsed)
