"""SARJ097 — Constant names and values should expose facts supplied only by comments.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_self_documenting_constant.py
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
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
from sarj_python_lint.rules._comments import split_identifier, standalone_comments
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path


_CONSTANT_NAME_RE = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
_MIN_BARE_HTTP_STATUSES = 2
_HTTP_STATUS_MIN = 100
_HTTP_STATUS_MAX = 599
_TRAILING_NUMBER_RE = re.compile(r"([-+]?\d[\d_]*(?:\.\d[\d_]*)?)\s*(?:[-–—]\s*)?$")
_UNIT_CONTEXT_RE = re.compile(r"(?:\b(?:in|as)\s+|\b(?:expressed|given|measured)\s+in\s+)$", re.IGNORECASE)
_HTTP_STATUS_IN_COMMENT_RE = re.compile(r"(?<!\d)([1-5]\d{2})(?!\d)")
_DIRECTIVE_RE = re.compile(
    r"^(?:todo|fixme|hack\b|xxx|note:|nb:|warning:|important:|noqa|sarj-noqa|"
    r"type:|pragma|pyright|mypy|fmt:|isort|ruff|pylint|flake8|coverage:|nosec|nosemgrep|"
    r"-\*-|!/|coding[:=])",
    re.IGNORECASE,
)
_ENUM_BASE_NAMES = frozenset({"Enum", "Flag", "IntEnum", "IntFlag", "StrEnum"})
_POLICY_SENTINEL_RE = re.compile(
    r"\b(?:disabled?|unlimited|unknown|inherit(?:ed)?|unset|absent|sentinel|no\s+limit|never)\b",
    re.IGNORECASE,
)

_SMALL_NUMBER_WORDS = MappingProxyType(
    {
        "zero": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
        "twenty": 20,
        "thirty": 30,
        "forty": 40,
        "fifty": 50,
        "sixty": 60,
        "seventy": 70,
        "eighty": 80,
        "ninety": 90,
    }
)
_HUNDRED_SCALE = 100
_NUMBER_SCALES = MappingProxyType({"hundred": _HUNDRED_SCALE, "thousand": 1000})
_NUMBER_WORD = "|".join((*_SMALL_NUMBER_WORDS, *_NUMBER_SCALES))
_TRAILING_NUMBER_WORD_RE = re.compile(
    rf"\b((?:(?:{_NUMBER_WORD})(?:[\s-]+|$))+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _Unit:
    label: str
    comment: re.Pattern[str]
    name_tokens: frozenset[str]
    suffix: str
    duration: bool = False


def _words(*values: str) -> frozenset[str]:
    return frozenset(values)


# These units are intentionally finite; a new noun belongs here only after corpus
# evidence shows that it is a unit, rather than merely a word near a number.
_UNITS: tuple[_Unit, ...] = (
    _Unit(
        "nanoseconds",
        re.compile(r"\b(?:nanoseconds?|nsecs?)\b|(?<=\d)\s*ns\b", re.IGNORECASE),
        _words("nanosecond", "nanoseconds", "nsec", "nsecs", "ns"),
        "NANOSECONDS",
        duration=True,
    ),
    _Unit(
        "microseconds",
        re.compile(r"\b(?:microseconds?|usecs?)\b|(?<=\d)\s*(?:us|µs)\b", re.IGNORECASE),
        _words("microsecond", "microseconds", "usec", "usecs", "us"),
        "MICROSECONDS",
        duration=True,
    ),
    _Unit(
        "milliseconds",
        re.compile(r"\b(?:milliseconds?|msecs?)\b|(?<=\d)\s*ms\b", re.IGNORECASE),
        _words("millisecond", "milliseconds", "msec", "msecs", "millis", "ms"),
        "MILLISECONDS",
        duration=True,
    ),
    _Unit(
        "seconds",
        re.compile(r"\b(?:seconds?|secs?)\b|(?<=\d)\s*s\b", re.IGNORECASE),
        _words("second", "seconds", "sec", "secs", "s"),
        "SECONDS",
        duration=True,
    ),
    _Unit(
        "minutes",
        re.compile(r"\b(?:minutes?|mins?)\b|(?<=\d)\s*m\b", re.IGNORECASE),
        _words("minute", "minutes", "min", "mins", "m"),
        "MINUTES",
        duration=True,
    ),
    _Unit(
        "hours",
        re.compile(r"\b(?:hours?|hrs?)\b|(?<=\d)\s*h\b", re.IGNORECASE),
        _words("hour", "hours", "hr", "hrs", "h"),
        "HOURS",
        duration=True,
    ),
    _Unit("days", re.compile(r"\bdays?\b", re.IGNORECASE), _words("day", "days"), "DAYS", duration=True),
    _Unit("bytes", re.compile(r"\bbytes?\b", re.IGNORECASE), _words("byte", "bytes"), "BYTES"),
    _Unit(
        "kilobytes",
        re.compile(r"\b(?:kilobytes?|kbytes?|kb)\b", re.IGNORECASE),
        _words("kilobyte", "kilobytes", "kbyte", "kbytes", "kb"),
        "KILOBYTES",
    ),
    _Unit(
        "kibibytes",
        re.compile(r"\b(?:kibibytes?|kib)\b", re.IGNORECASE),
        _words("kibibyte", "kibibytes", "kib"),
        "KIBIBYTES",
    ),
    _Unit(
        "megabytes",
        re.compile(r"\b(?:megabytes?|mbytes?|mb)\b", re.IGNORECASE),
        _words("megabyte", "megabytes", "mbyte", "mbytes", "mb"),
        "MEGABYTES",
    ),
    _Unit(
        "mebibytes",
        re.compile(r"\b(?:mebibytes?|mib)\b", re.IGNORECASE),
        _words("mebibyte", "mebibytes", "mib"),
        "MEBIBYTES",
    ),
    _Unit(
        "gigabytes",
        re.compile(r"\b(?:gigabytes?|gbytes?|gb)\b", re.IGNORECASE),
        _words("gigabyte", "gigabytes", "gbyte", "gbytes", "gb"),
        "GIGABYTES",
    ),
    _Unit(
        "gibibytes",
        re.compile(r"\b(?:gibibytes?|gib)\b", re.IGNORECASE),
        _words("gibibyte", "gibibytes", "gib"),
        "GIBIBYTES",
    ),
    _Unit("bits", re.compile(r"\bbits?\b", re.IGNORECASE), _words("bit", "bits"), "BITS"),
    _Unit(
        "percent",
        re.compile(r"\b(?:percent(?:age)?|pct)\b|(?<=\d)\s*%", re.IGNORECASE),
        _words("percent", "percentage", "pct"),
        "PERCENT",
    ),
    _Unit("pixels", re.compile(r"\b(?:pixels?|px)\b", re.IGNORECASE), _words("pixel", "pixels", "px"), "PIXELS"),
    _Unit(
        "attempts",
        re.compile(r"\battempts?\b", re.IGNORECASE),
        _words("attempt", "attempts", "retry", "retries"),
        "ATTEMPTS",
    ),
    _Unit("rows", re.compile(r"\brows?\b", re.IGNORECASE), _words("row", "rows", "record", "records"), "ROWS"),
)
_ALL_UNIT_NAME_TOKENS = frozenset(token for unit in _UNITS for token in unit.name_tokens)
_CONFLICT_UNIT_NAME_TOKENS = _ALL_UNIT_NAME_TOKENS - {"record", "records", "retries", "retry"}


@final
class PreferSelfDocumentingConstant(Rule):
    id = "prefer-self-documenting-constant"
    code = "SARJ097"
    documentation = RuleDocumentation(
        summary="Encode a constant's units or HTTP status meaning in its name, type, or value.",
        rationale="A comment-only fact is lost at use sites and can drift independently from the constant it describes.",
        remediation="Add the unit to the name or type, use a unit-bearing value such as `timedelta`, or replace status integers with `HTTPStatus` members.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct module and class constants with attached comments and proven numeric or HTTP-status shapes are analyzed.",
            "Generated code, directives, ambiguous comments, policy sentinels, and values already carrying the fact are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="comment-only-constant-unit",
                title="Comment is the only source of the unit",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        "# Request deadline in seconds.\nREQUEST_DEADLINE = 10\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="unit-bearing-constant-name",
                title="Constant name carries its unit",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        "# Request deadline in seconds.\nREQUEST_DEADLINE_SECONDS = 10\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        comments, _first_code_line = standalone_comments(source)
        by_line = {line: (col, body) for line, col, body in comments}
        findings: list[Diagnostic] = []
        for statement, name, value in _constant_bindings(tree):
            comment = _attached_comment(statement, by_line)
            if comment is None:
                continue
            statuses = _bare_http_statuses(value)
            if (
                _is_status_codes_name(name)
                and len(statuses) >= _MIN_BARE_HTTP_STATUSES
                and len(statuses & _comment_http_statuses(comment)) >= _MIN_BARE_HTTP_STATUSES
            ):
                findings.append(
                    Diagnostic(
                        path,
                        statement.lineno,
                        statement.col_offset + 1,
                        self.code,
                        (
                            f"`{name}` contains bare HTTP status integers; use `http.HTTPStatus` "
                            "members so each value is self-documenting, while preserving non-obvious rationale."
                        ),
                        Severity.ERROR,
                    )
                )
                continue
            scalar = _numeric_scalar(value)
            if scalar is None:
                continue
            if scalar in {-1, 0} and _POLICY_SENTINEL_RE.search(comment):
                continue
            unit = _missing_unit(statement, name, comment, scalar)
            if unit is None:
                continue
            alternative = " or use a unit-bearing type such as `timedelta`" if unit.duration else ""
            compatibility = ", preserving public compatibility if it is exported" if not name.startswith("_") else ""
            findings.append(
                Diagnostic(
                    path,
                    statement.lineno,
                    statement.col_offset + 1,
                    self.code,
                    (
                        f"`{name}` relies on its comment to identify {unit.label}; encode the unit in "
                        f"the constant name{alternative}{compatibility}, while preserving non-obvious rationale."
                    ),
                    Severity.ERROR,
                )
            )
        return findings


def _constant_bindings(tree: ast.Module) -> Iterator[tuple[ast.Assign | ast.AnnAssign, str, ast.expr]]:
    bindings: list[tuple[ast.Assign | ast.AnnAssign, str, ast.expr]] = []

    def collect(owner: ast.Module | ast.ClassDef) -> None:
        if isinstance(owner, ast.ClassDef) and _is_enum_class(owner):
            return
        for statement in owner.body:
            if isinstance(statement, ast.ClassDef):
                collect(statement)
                continue
            match statement:
                case ast.Assign(targets=[ast.Name(id=name)], value=value):
                    pass
                case ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value, simple=1):
                    pass
                case _:
                    continue
            if _CONSTANT_NAME_RE.fullmatch(name) and not name.startswith("__"):
                bindings.append((statement, name, value))

    collect(tree)
    yield from sorted(bindings, key=lambda binding: (binding[0].lineno, binding[0].col_offset))


def _attached_comment(statement: ast.stmt, by_line: dict[int, tuple[int, str]]) -> str | None:
    cursor = statement.lineno - 1
    entry = by_line.get(cursor)
    if entry is None or entry[0] != statement.col_offset:
        return None
    bodies: list[str] = []
    while (entry := by_line.get(cursor)) is not None and entry[0] == statement.col_offset:
        bodies.append(entry[1])
        cursor -= 1
    bodies.reverse()
    if any(_DIRECTIVE_RE.match(body) for body in bodies):
        return None
    return " ".join(bodies)


def _missing_unit(statement: ast.Assign | ast.AnnAssign, name: str, comment: str, value: float) -> _Unit | None:
    declaration_tokens = set(split_identifier(name))
    if isinstance(statement, ast.AnnAssign):
        declaration_tokens.update(_annotation_tokens(statement.annotation))
    mentioned = tuple(unit for unit in _UNITS if _comment_assigns_unit(comment, unit, value))
    # A name carrying a different unit is contradictory, but appending a second
    # suffix would worsen it; leave the conflict to a dedicated future rule.
    mentioned_name_tokens = frozenset(token for unit in mentioned for token in unit.name_tokens)
    if declaration_tokens & (_CONFLICT_UNIT_NAME_TOKENS - mentioned_name_tokens):
        return None
    # A rationale can mention several quantities; once the name identifies one,
    # guessing that another quantity is the assigned value is unsafe.
    if any(not declaration_tokens.isdisjoint(unit.name_tokens) for unit in mentioned):
        return None
    return mentioned[0] if len(mentioned) == 1 else None


def _comment_assigns_unit(comment: str, unit: _Unit, value: float) -> bool:
    for match in unit.comment.finditer(comment):
        prefix = comment[: match.start()]
        number_match = _TRAILING_NUMBER_RE.search(prefix)
        if number_match is not None and _numbers_equal(number_match.group(1), value):
            return True
        word_match = _TRAILING_NUMBER_WORD_RE.search(prefix)
        if word_match is not None and _number_words(word_match.group(1)) == value:
            return True
        if _UNIT_CONTEXT_RE.search(prefix):
            return True
    return False


def _numeric_scalar(value: ast.expr) -> int | float | None:
    match value:
        case ast.Constant(value=number) if isinstance(number, (int, float)) and not isinstance(number, bool):
            return number
        case ast.UnaryOp(op=ast.USub() | ast.UAdd(), operand=ast.Constant(value=number)) if isinstance(
            number, (int, float)
        ) and not isinstance(number, bool):
            return -number if isinstance(value.op, ast.USub) else number
        case _:
            return None


def _is_status_codes_name(name: str) -> bool:
    tokens = frozenset(split_identifier(name))
    return "status" in tokens and not tokens.isdisjoint({"code", "codes"})


def _bare_http_statuses(value: ast.expr) -> frozenset[int]:
    elements: Sequence[ast.expr]
    match value:
        case ast.List() | ast.Set() | ast.Tuple():
            elements = value.elts
        case ast.Call(
            func=func, args=[ast.List(elts=items) | ast.Set(elts=items) | ast.Tuple(elts=items)], keywords=[]
        ):
            if not _is_frozenset_constructor(func):
                return frozenset()
            elements = items
        case ast.Dict(keys=keys):
            elements = [key for key in keys if key is not None]
        case _:
            return frozenset()
    if not all(
        isinstance(item, ast.Constant)
        and isinstance(item.value, int)
        and not isinstance(item.value, bool)
        and _HTTP_STATUS_MIN <= item.value <= _HTTP_STATUS_MAX
        for item in elements
    ):
        return frozenset()
    statuses: set[int] = set()
    for item in elements:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, int):
            return frozenset()
        statuses.add(item.value)
    return frozenset(statuses)


def _comment_http_statuses(comment: str) -> frozenset[int]:
    return frozenset(int(match.group(1)) for match in _HTTP_STATUS_IN_COMMENT_RE.finditer(comment))


def _annotation_tokens(annotation: ast.expr) -> set[str]:
    tokens: set[str] = set()
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name):
            tokens.update(split_identifier(node.id))
        elif isinstance(node, ast.Attribute):
            tokens.update(split_identifier(node.attr))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            tokens.update(split_identifier(node.value))
    return tokens


def _numbers_equal(comment_number: str, value: float) -> bool:
    try:
        return Decimal(comment_number.replace("_", "")) == Decimal(str(value))
    except InvalidOperation:
        return False


def _number_words(text: str) -> int | None:
    words: list[str] = re.findall(r"[a-z]+", text.casefold())
    if not words:
        return None
    current = 0
    total = 0
    for word in words:
        if word in _SMALL_NUMBER_WORDS:
            current += _SMALL_NUMBER_WORDS[word]
        elif (scale := _NUMBER_SCALES.get(word)) is not None:
            if current == 0:
                return None
            if scale == _HUNDRED_SCALE:
                current *= scale
            else:
                total += current * scale
                current = 0
        else:
            return None
    return total + current


def _is_enum_class(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = _trailing_name(base)
        if name in _ENUM_BASE_NAMES or (name is not None and name.endswith(("Enum", "Flag"))):
            return True
    return False


def _is_frozenset_constructor(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "frozenset") or (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "builtins"
        and node.attr == "frozenset"
    )


def _trailing_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None
