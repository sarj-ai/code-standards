from __future__ import annotations

import ast
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
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
from sarj_python_lint.rules._imports import ImportIndex
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
_HTTP_CONTEXT_RE = re.compile(r"\bhttp(?:s)?\b", re.IGNORECASE)
_OTHER_STATUS_PROTOCOL_RE = re.compile(
    r"\b(?:smtp|sip|ftp|sftp|ssh|grpc|websocket|device|modbus|diameter)\b", re.IGNORECASE
)
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
_STANDARD_HTTP_STATUSES = frozenset(status.value for status in HTTPStatus)
_GENERIC_VALUE_TOKENS = frozenset({"constant", "value"})
_CLAUSE_BOUNDARY_RE = re.compile(r"(?:[.,;:]|[–—]|\n+|\s-{1,2}\s|\b(?:and|but|while)\b)\s*", re.IGNORECASE)
_IDENTIFIER_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

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
        re.compile(r"\b(?:minutes?|mins?)\b", re.IGNORECASE),
        _words("minute", "minutes", "min", "mins"),
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
_CONFLICT_UNIT_NAME_TOKENS = _ALL_UNIT_NAME_TOKENS - {"record", "retry"}


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
            "Generated code, directives, ambiguous comments, policy sentinels, non-HTTP protocols, vendor status codes, and values already carrying the fact are excluded; tests remain in scope.",
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
                        "# The upstream gateway closes idle requests first.\nREQUEST_DEADLINE_SECONDS = 10\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="bare-http-status-collection",
                scenario="http-status",
                title="HTTP status collection uses bare integers",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/retry.py",
                        "# Retry HTTP responses 408 and 429.\nRETRYABLE_HTTP_STATUS_CODES = {408, 429}\n",
                    ),
                ),
                focus_path=PurePosixPath("app/retry.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="named-http-status-collection",
                scenario="http-status",
                title="HTTP status members carry protocol meaning",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/retry.py",
                        "from http import HTTPStatus\n\n"
                        "RETRYABLE_HTTP_STATUS_CODES = {\n"
                        "    HTTPStatus.REQUEST_TIMEOUT,\n"
                        "    HTTPStatus.TOO_MANY_REQUESTS,\n"
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("app/retry.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        if not _has_syntactic_candidate(tree):
            return []
        imports = ImportIndex.from_tree(tree)
        enum_class_ids = _enum_class_ids(tree, imports)
        bindings = [
            binding
            for binding in _constant_bindings(tree, enum_class_ids)
            if _numeric_scalar(binding[2]) is not None or _looks_like_status_collection(binding[2])
        ]
        if not bindings or is_generated(path, source):
            return []
        frozenset_risks = (_has_wildcard_import(tree), _builtins_frozenset_mutated(tree, imports))
        comments, _first_code_line = standalone_comments(source)
        by_line = {line: (col, body) for line, col, body in comments}
        findings: list[Diagnostic] = []
        for statement, name, value in bindings:
            comment = _attached_comment(statement, by_line)
            if comment is None:
                continue
            statuses = _bare_http_statuses(
                value,
                imports,
                wildcard_import=frozenset_risks[0],
                builtins_frozenset_mutated=frozenset_risks[1],
            )
            if (
                _is_status_codes_name(name)
                and len(statuses) >= _MIN_BARE_HTTP_STATUSES
                and statuses <= _STANDARD_HTTP_STATUSES
                and _has_http_context(name, comment)
                and len(statuses & _comment_http_statuses(comment)) >= _MIN_BARE_HTTP_STATUSES
            ):
                findings.append(
                    Diagnostic(
                        path,
                        statement.lineno,
                        statement.col_offset + 1,
                        self.code,
                        (
                            f"`{name}` contains bare HTTP status integers; use `http.HTTPStatus` members, "
                            "or their `.value` at an exact-integer boundary. Keep non-obvious rationale."
                        ),
                        Severity.WARNING,
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
            compatibility = (
                " If this exported name is public API, migrate compatibly." if not name.startswith("_") else ""
            )
            findings.append(
                Diagnostic(
                    path,
                    statement.lineno,
                    statement.col_offset + 1,
                    self.code,
                    (
                        f"`{name}` relies on its comment to identify {unit.label}; encode the unit in "
                        f"the constant name{alternative}.{compatibility} Keep non-obvious rationale."
                    ),
                    Severity.WARNING,
                )
            )
        return findings


def _constant_bindings(
    tree: ast.Module, enum_class_ids: frozenset[int]
) -> Iterator[tuple[ast.Assign | ast.AnnAssign, str, ast.expr]]:
    bindings: list[tuple[ast.Assign | ast.AnnAssign, str, ast.expr]] = []

    def collect(owner: ast.Module | ast.ClassDef) -> None:
        if isinstance(owner, ast.ClassDef) and id(owner) in enum_class_ids:
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


def _has_syntactic_candidate(tree: ast.Module) -> bool:
    return any(
        _numeric_scalar(value) is not None or _looks_like_status_collection(value)
        for _statement, _name, value in _constant_bindings(tree, frozenset())
    )


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
    return "\n".join(bodies)


def _missing_unit(statement: ast.Assign | ast.AnnAssign, name: str, comment: str, value: float) -> _Unit | None:
    declaration_tokens = set(split_identifier(name))
    if isinstance(statement, ast.AnnAssign):
        declaration_tokens.update(_annotation_tokens(statement.annotation))
    mentioned = tuple(unit for unit in _UNITS if _comment_assigns_unit(comment, unit, value, declaration_tokens))
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


def _comment_assigns_unit(comment: str, unit: _Unit, value: float, declaration_tokens: set[str]) -> bool:
    for match in unit.comment.finditer(comment):
        prefix = comment[: match.start()]
        number_match = _TRAILING_NUMBER_RE.search(prefix)
        if number_match is not None and _numbers_equal(number_match.group(1), value):
            return True
        word_match = _TRAILING_NUMBER_WORD_RE.search(prefix)
        if word_match is not None and _number_words(word_match.group(1)) == value:
            return True
        if _UNIT_CONTEXT_RE.search(prefix) and _context_names_constant(prefix, declaration_tokens):
            return True
    return False


def _context_names_constant(prefix: str, declaration_tokens: set[str]) -> bool:
    clause = _CLAUSE_BOUNDARY_RE.split(prefix)[-1]
    clause_tokens = {
        token for match in _IDENTIFIER_WORD_RE.finditer(clause) for token in split_identifier(match.group(0))
    }
    return not clause_tokens.isdisjoint(declaration_tokens | _GENERIC_VALUE_TOKENS)


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


def _looks_like_status_collection(value: ast.expr) -> bool:
    match value:
        case (
            ast.List()
            | ast.Set()
            | ast.Tuple()
            | ast.Dict()
            | ast.Call(args=[ast.List() | ast.Set() | ast.Tuple()], keywords=[])
        ):
            return True
        case _:
            return False


def _bare_http_statuses(
    value: ast.expr,
    imports: ImportIndex,
    *,
    wildcard_import: bool,
    builtins_frozenset_mutated: bool,
) -> frozenset[int]:
    elements: Sequence[ast.expr]
    match value:
        case ast.List() | ast.Set() | ast.Tuple():
            elements = value.elts
        case ast.Call(
            func=func, args=[ast.List(elts=items) | ast.Set(elts=items) | ast.Tuple(elts=items)], keywords=[]
        ):
            if not _is_frozenset_constructor(
                func,
                imports,
                wildcard_import=wildcard_import,
                builtins_frozenset_mutated=builtins_frozenset_mutated,
            ):
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


def _has_http_context(name: str, comment: str) -> bool:
    combined = f"{name} {comment}"
    return (
        "http" in split_identifier(name) or _HTTP_CONTEXT_RE.search(comment) is not None
    ) and _OTHER_STATUS_PROTOCOL_RE.search(combined) is None


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


def _enum_class_ids(tree: ast.Module, imports: ImportIndex) -> frozenset[int]:
    aliases = _enum_aliases(tree, imports)
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    enum_names = set(aliases)
    enum_ids: set[int] = set()
    changed = True
    while changed:
        changed = False
        for node in classes:
            if id(node) in enum_ids or not any(_is_enum_base(base, imports, enum_names) for base in node.bases):
                continue
            enum_ids.add(id(node))
            enum_names.add(node.name)
            changed = True
    return frozenset(enum_ids)


def _enum_aliases(tree: ast.Module, imports: ImportIndex) -> frozenset[str]:
    aliases: set[str] = set()
    changed = True
    while changed:
        changed = False
        for statement in tree.body:
            match statement:
                case ast.Assign(targets=[ast.Name(id=name)], value=value):
                    pass
                case ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value, simple=1):
                    pass
                case _:
                    continue
            if name not in aliases and _is_enum_base(value, imports, aliases):
                aliases.add(name)
                changed = True
    return frozenset(aliases)


def _is_enum_base(node: ast.expr, imports: ImportIndex, local_names: set[str] | frozenset[str]) -> bool:
    trailing = _trailing_name(node)
    if (
        trailing in local_names
        or trailing in _ENUM_BASE_NAMES
        or (trailing is not None and trailing.endswith(("Enum", "Flag")))
    ):
        return True
    return any(imports.resolves(node, sources=frozenset({"enum"}), symbol=name) for name in _ENUM_BASE_NAMES)


def _is_frozenset_constructor(
    node: ast.expr,
    imports: ImportIndex,
    *,
    wildcard_import: bool,
    builtins_frozenset_mutated: bool,
) -> bool:
    if builtins_frozenset_mutated:
        return False
    if isinstance(node, ast.Name) and node.id == "frozenset":
        return not wildcard_import and imports.builtin_is_unshadowed("frozenset")
    return imports.resolves(node, sources=frozenset({"builtins"}), symbol="frozenset")


def _has_wildcard_import(tree: ast.Module) -> bool:
    return any(
        isinstance(statement, ast.ImportFrom) and any(alias.name == "*" for alias in statement.names)
        for statement in tree.body
    )


def _builtins_frozenset_mutated(tree: ast.Module, imports: ImportIndex) -> bool:
    return any(
        isinstance(node, ast.Attribute)
        and isinstance(node.ctx, (ast.Store, ast.Del))
        and imports.resolves(node, sources=frozenset({"builtins"}), symbol="frozenset")
        for node in ast.walk(tree)
    )


def _trailing_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None
