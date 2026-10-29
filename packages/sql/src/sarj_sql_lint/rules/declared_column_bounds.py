from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, Final, final, override

from sqlglot import exp

from sarj_sql_lint.rule_base import (
    AutofixPolicy,
    DefaultLevel,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_dump_file,
    is_generated_migration,
    is_postgres_migration,
    mask_sql,
    source_location,
)
from sarj_sql_lint.rules._column_contracts import (
    bare_column,
    child,
    column_key,
    column_offset,
    table_contracts,
    unparenthesize,
)


if TYPE_CHECKING:
    from pathlib import Path


_NUMBER = r"-?\d+(?:\.\d+)?"
_ALTER_TABLE = re.compile(r"\bALTER\s+TABLE\b", re.IGNORECASE)
_RANGE = re.compile(
    rf"(?<![\w.])(?P<low>{_NUMBER})(?P<low_unit>ms|s|m|h|d|w)?\s*\.\.\s*"
    rf"(?P<high>{_NUMBER})(?P<high_unit>ms|s|m|h|d|w)?(?![\w.])",
    re.IGNORECASE,
)
_RANGE_LABEL = re.compile(r"\b(?:range|capped|allowed|valid|between)\b", re.IGNORECASE)
_AMBIGUOUS_DECLARATION = re.compile(
    r"\b(?:if|when|unless|except|previous|previously|formerly|historical|was|now|not|may|might)\b|\b(?:used to|no longer)\b",
    re.IGNORECASE,
)
_POSITIVE = re.compile(r"(?:^|[;:])\s*(?:strictly\s+)?positive\b|\bmust be (?:strictly )?positive\b", re.IGNORECASE)
_NONNEGATIVE = re.compile(r"(?:^|[;:])\s*non[ -]?negative\b|\bmust be non[ -]?negative\b", re.IGNORECASE)
_INTERVAL_VALUE = re.compile(rf"\s*({_NUMBER})\s*([A-Za-z]+)\s*")
_SECONDS: Final[dict[str, Decimal]] = {
    "ms": Decimal("0.001"),
    "millisecond": Decimal("0.001"),
    "milliseconds": Decimal("0.001"),
    "s": Decimal(1),
    "second": Decimal(1),
    "seconds": Decimal(1),
    "m": Decimal(60),
    "minute": Decimal(60),
    "minutes": Decimal(60),
    "h": Decimal(3600),
    "hour": Decimal(3600),
    "hours": Decimal(3600),
    "d": Decimal(86400),
    "day": Decimal(86400),
    "days": Decimal(86400),
    "w": Decimal(604800),
    "week": Decimal(604800),
    "weeks": Decimal(604800),
}
_INTEGERS = frozenset({"SMALLINT", "INT", "BIGINT", "TINYINT"})
_NUMERIC = _INTEGERS | {"DECIMAL", "DOUBLE", "FLOAT"}


@dataclass(frozen=True, slots=True)
class _Bound:
    value: Decimal
    inclusive: bool = True


@dataclass(frozen=True, slots=True)
class _Bounds:
    low: _Bound | None = None
    high: _Bound | None = None


@final
class DeclaredColumnBounds(Rule):
    id = "declared-column-bounds"
    code = "SARJ130"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="Encode explicitly declared numeric and interval ranges in SQL CHECK constraints.",
        rationale=(
            "A column comment declaring a range does not reject out-of-range writes. Encoding that explicit "
            "contract in CHECK constraints keeps every writer subject to the same bounds."
        ),
        remediation=(
            "Replace the range comment with an inline CHECK that enforces the declared bounds. Preserve units, "
            "inclusive endpoints and nullability. Do not invent a positive bound from a column name."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks authored PostgreSQL migration CREATE TABLE columns with an attached range comment: labeled numeric a..b, explicit interval a-unit..b-unit, or explicit positive/non-negative declarations. Arbitrary names, defaults, signed amounts, offsets and undocumented limits do not imply a bound.",
            "Understands literal numeric comparisons, BETWEEN, reversed comparisons and AND in inline/table CHECK constraints. Integer exclusive endpoints are normalized. Simple constant intervals use milliseconds through weeks; calendar months/years, casts on columns and computed bounds are not inferred.",
            "Unknown CHECK expressions mentioning the column cause abstention, rather than a false claim that a complex constraint is missing. Files containing ALTER TABLE are excluded because staged constraints are not resolved. Domains, generated migrations and dumps are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="comment-only-range",
                title="A comment cannot enforce a declared numeric range",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_retry.sql",
                        "CREATE TABLE retry (\n  attempts INTEGER NOT NULL -- required; capped 1..10\n);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_retry.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="encoded-range",
                title="CHECK encodes the permitted range without commentary",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_retry.sql",
                        "CREATE TABLE retry (attempts INTEGER NOT NULL CHECK (attempts BETWEEN 1 AND 10));\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_retry.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            not any(marker in source for marker in ("--", "/*"))
            or not is_postgres_migration(path, source)
            or is_dump_file(source, path)
            or is_generated_migration(path, source)
        ):
            return []
        if _ALTER_TABLE.search(mask_sql(source, mask_dollar_literals=True)) is not None:
            return []
        findings: list[Diagnostic] = []
        for table in table_contracts(source):
            for column in table.columns:
                if not _missing_bounds(column, table.checks):
                    continue
                location = source_location(source, table.offset + column_offset(column))
                findings.append(
                    Diagnostic(
                        path,
                        location.line,
                        location.column,
                        self.code,
                        f"Column `{column_key(column)}` declares a range in a comment without CHECK constraints proving those bounds. "
                        "Encode the declared range in SQL, preserving units and nullability, then remove the comment.",
                        DefaultLevel.WARNING,
                    )
                )
        return findings


def _missing_bounds(column: exp.ColumnDef, checks: tuple[exp.Expr, ...]) -> bool:
    kind = column.kind.sql(comments=False).partition("(")[0] if isinstance(column.kind, exp.DataType) else ""
    if kind not in _NUMERIC | {"INTERVAL"}:
        return False
    comments = [comment for node in column.walk() for comment in node.comments or []]
    expected = _declared_bounds(comments, interval=kind == "INTERVAL")
    if expected is None:
        return False
    name = column_key(column)
    actual = [_check_bounds(check, name, interval=kind == "INTERVAL") for check in checks]
    if any(bounds is None for bounds in actual):
        return False
    return not _covered(expected, actual, integer=kind in _INTEGERS)


def _declared_bounds(comments: list[str], *, interval: bool) -> _Bounds | None:
    for comment in comments:
        if _AMBIGUOUS_DECLARATION.search(comment):
            continue
        if (match := _RANGE.search(comment)) is not None:
            low_unit, high_unit = match.group("low_unit"), match.group("high_unit")
            if interval and low_unit and high_unit:
                low = Decimal(match.group("low")) * _SECONDS[low_unit.lower()]
                high = Decimal(match.group("high")) * _SECONDS[high_unit.lower()]
            elif not interval and not low_unit and not high_unit and _RANGE_LABEL.search(comment):
                low, high = Decimal(match.group("low")), Decimal(match.group("high"))
            else:
                continue
            if low <= high:
                return _Bounds(_Bound(low), _Bound(high))
        if _NONNEGATIVE.search(comment):
            return _Bounds(_Bound(Decimal(0)))
        if _POSITIVE.search(comment):
            return _Bounds(_Bound(Decimal(0), inclusive=False))
    return None


def _check_bounds(node: exp.Expr | None, name: str, *, interval: bool) -> list[_Bounds] | None:
    if node is None:
        return None
    node = unparenthesize(node)
    if not any(column_key(column) == name for column in node.find_all(exp.Column)):
        return []
    if isinstance(node, exp.And):
        left = _check_bounds(child(node, "this"), name, interval=interval)
        right = _check_bounds(child(node, "expression"), name, interval=interval)
        return None if left is None or right is None else [*left, *right]
    left, right = child(node, "this"), child(node, "expression")
    if left is None:
        return None
    if isinstance(node, exp.Between) and bare_column(left, name):
        low = _constant(child(node, "low"), interval=interval)
        high = _constant(child(node, "high"), interval=interval)
        return [_Bounds(_Bound(low), _Bound(high))] if low is not None and high is not None else None
    if not isinstance(node, exp.GT | exp.GTE | exp.LT | exp.LTE | exp.EQ):
        return None
    if right is None:
        return None
    reverse = not bare_column(unparenthesize(left), name)
    column, literal = (right, left) if reverse else (left, right)
    value = _constant(literal, interval=interval)
    if value is None or not bare_column(unparenthesize(column), name):
        return None
    bound = _Bound(value, inclusive=not isinstance(node, exp.GT | exp.LT))
    if isinstance(node, exp.EQ):
        return [_Bounds(bound, bound)]
    lower = isinstance(node, exp.GT | exp.GTE) != reverse
    return [_Bounds(low=bound) if lower else _Bounds(high=bound)]


def _constant(node: exp.Expr | None, *, interval: bool) -> Decimal | None:
    if node is None:
        return None
    node = unparenthesize(node)
    if interval:
        return _interval_constant(node)
    if isinstance(node, exp.Literal) and not node.is_string:
        return _decimal(node.name)
    if isinstance(node, exp.Neg):
        value = _constant(child(node, "this"), interval=False)
        return -value if value is not None else None
    return None


def _interval_constant(node: exp.Expr) -> Decimal | None:
    literal = child(node, "this")
    if not isinstance(literal, exp.Literal):
        return None
    if isinstance(node, exp.Interval):
        unit = child(node, "unit")
        factor = _SECONDS.get(unit.name.lower()) if isinstance(unit, exp.Expr) else None
        value = _decimal(literal.name)
        return value * factor if factor is not None and value is not None else None
    if isinstance(node, exp.Cast) and node.to.is_type(exp.DataType.Type.INTERVAL):
        match = _INTERVAL_VALUE.fullmatch(literal.name)
        if match is not None and (factor := _SECONDS.get(match.group(2).lower())) is not None:
            return Decimal(match.group(1)) * factor
    return None


def _decimal(value: str) -> Decimal | None:
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _covered(expected: _Bounds, checks: list[list[_Bounds] | None], *, integer: bool) -> bool:
    actual = [bound for check in checks if check is not None for bound in check]
    return all(
        wanted is None
        or any(
            found is not None and _stronger(found, wanted, lower=lower, integer=integer)
            for bound in actual
            if (found := bound.low if lower else bound.high) is not None
        )
        for lower, wanted in ((True, expected.low), (False, expected.high))
    )


def _stronger(actual: _Bound, expected: _Bound, *, lower: bool, integer: bool) -> bool:
    if integer:
        actual = _integer_bound(actual, lower=lower)
        expected = _integer_bound(expected, lower=lower)
    if actual.value == expected.value:
        return expected.inclusive or not actual.inclusive
    return actual.value > expected.value if lower else actual.value < expected.value


def _integer_bound(bound: _Bound, *, lower: bool) -> _Bound:
    value = bound.value.to_integral_value(rounding=ROUND_CEILING if lower else ROUND_FLOOR)
    if not bound.inclusive and value == bound.value:
        value += 1 if lower else -1
    return _Bound(value)
