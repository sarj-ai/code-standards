from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date
import re
from typing import TYPE_CHECKING, TypeIs

from sarj_rule_contracts import RuleId, TextEdit
from sqlglot import exp

from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.rule_base import physical_lines


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sarj_sql_lint.rule_base import Diagnostic


_SPACE = r"[ \t\r\n\f]*"
_SEPARATOR = r"[ \t\r\n\f]+"
_PLAIN_STRING = re.compile(r"'[\x20-\x26\x28-\x5b\x5d-\x7e]*'")
_TYPE = re.compile(
    rf"pg_catalog{_SPACE}\.{_SPACE}(?P<name>varchar|text|jsonb?|timestamptz|timestamp)\b"
    rf"(?:{_SPACE}\({_SPACE}(?P<bound>[0-9]+){_SPACE}\))?",
    re.IGNORECASE,
)
_ISO_TIMESTAMP = r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}"
_NAIVE_CAST = (
    rf"CAST{_SPACE}\({_SPACE}(?P<literal>'{_ISO_TIMESTAMP}'){_SEPARATOR}AS{_SEPARATOR}"
    rf"pg_catalog{_SPACE}\.{_SPACE}timestamp{_SPACE}\)"
)
_ZERO_INTERVAL = rf"INTERVAL{_SEPARATOR}'00:00'"
_TIMEZONE_FORMS = (
    re.compile(
        rf"pg_catalog{_SPACE}\.{_SPACE}timezone{_SPACE}\({_SPACE}{_ZERO_INTERVAL}{_SPACE},"
        rf"{_SPACE}{_NAIVE_CAST}{_SPACE}\)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"{_NAIVE_CAST}{_SEPARATOR}AT{_SEPARATOR}TIME{_SEPARATOR}ZONE{_SEPARATOR}{_ZERO_INTERVAL}",
        re.IGNORECASE,
    ),
)
_MAX_VARCHAR_BOUND = 10_485_760
_MAX_BOUND_DIGITS = 8
_TIMEZONE_ARGUMENT_COUNT = 2
_HOURS_PER_DAY = 24
_MINUTES_PER_HOUR = 60
_SECONDS_PER_MINUTE = 60
_UNBOUNDED_TYPES = frozenset({"text", "json", "jsonb", "timestamp", "timestamptz"})
_SELECT_ARGUMENTS = frozenset({"expressions"})
_CREATE_ARGUMENTS = frozenset({"this", "kind", "exists"})
_COLUMN_ARGUMENTS = frozenset({"this", "kind", "constraints"})


@dataclass(frozen=True, slots=True)
class _Range:
    start: int
    end: int


def literal_edits(source: str, diagnostics: Sequence[Diagnostic], rule_id: RuleId) -> list[TextEdit]:
    if not diagnostics:
        return []
    statements = [tree for tree in parse_postgres(source) if tree is not None]
    if len(statements) != 1 or not _literal_statement(source, statements[0]):
        return []
    lines = physical_lines(source, keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    positions = sorted({offsets[item.line - 1] + item.col - 1 for item in diagnostics if 0 < item.line <= len(lines)})
    timezones = _timezone_ranges(source) if rule_id == "enforce-timestamptz" else {}
    return [
        edit
        for tree in statements
        for cast in tree.find_all(exp.Cast)
        if (edit := _literal_edit(source, cast, positions, timezones, rule_id=rule_id)) is not None
    ]


def _literal_statement(source: str, node: exp.Expr) -> bool:
    if isinstance(node, exp.Select):
        projections = _expression_children(node)
        return (
            projections is not None
            and bool(projections)
            and _only_arguments(node, _SELECT_ARGUMENTS)
            and all(_literal_projection(source, item) for item in projections)
        )
    if not isinstance(node, exp.Create) or _arguments(node).get("kind") != "TABLE":
        return False
    schema = _arguments(node).get("this")
    if not isinstance(schema, exp.Schema) or not isinstance(_arguments(schema).get("this"), exp.Table):
        return False
    columns = _expression_children(schema)
    return (
        columns is not None
        and _only_arguments(node, _CREATE_ARGUMENTS)
        and all(_literal_column(source, column) for column in columns)
    )


def _only_arguments(node: exp.Expr, allowed: frozenset[str]) -> bool:
    return not any(value for key, value in _arguments(node).items() if key not in allowed)


def _literal_projection(source: str, node: exp.Expr) -> bool:
    if isinstance(node, exp.Alias):
        return isinstance(_arguments(node).get("alias"), exp.Identifier) and _literal_expression(
            source, _arguments(node).get("this")
        )
    return _literal_expression(source, node)


def _literal_column(source: str, node: exp.Expr) -> bool:
    if (
        not isinstance(node, exp.ColumnDef)
        or not isinstance(_arguments(node).get("this"), exp.Identifier)
        or not _canonical_type(source, _arguments(node).get("kind"))
        or not _only_arguments(node, _COLUMN_ARGUMENTS)
    ):
        return False
    constraints = _expression_children(node, "constraints")
    return (
        constraints is not None
        and len(constraints) <= 1
        and all(_literal_default(source, constraint) for constraint in constraints)
    )


def _literal_default(source: str, node: exp.Expr) -> bool:
    if not isinstance(node, exp.ColumnConstraint):
        return False
    kind = _arguments(node).get("kind")
    return (
        _arguments(node).get("this") is None
        and isinstance(kind, exp.DefaultColumnConstraint)
        and _literal_expression(source, _arguments(kind).get("this"))
    )


def _literal_expression(source: str, node: object) -> bool:
    if isinstance(node, (exp.Literal, exp.Boolean, exp.Null)):
        return True
    if isinstance(node, exp.Paren):
        return _literal_expression(source, _arguments(node).get("this"))
    if type(node) is exp.Cast:
        return _canonical_type(source, _arguments(node).get("to")) and _literal_expression(
            source, _arguments(node).get("this")
        )
    cast = _timezone_cast(node)
    literal = _arguments(cast).get("this") if cast is not None else None
    return (
        isinstance(cast, exp.Cast)
        and _catalog_type(_arguments(cast).get("to"), "timestamp")
        and isinstance(literal, exp.Literal)
        and (value := _plain_literal(source, literal)) is not None
        and _valid_iso_timestamp(value)
    )


def _timezone_cast(node: object) -> exp.Cast | None:
    candidate: object = None
    if isinstance(node, exp.AtTimeZone):
        candidate = _arguments(node).get("this")
    elif isinstance(node, exp.Dot):
        function = _arguments(node).get("expression")
        arguments = _expression_children(function) if isinstance(function, exp.Anonymous) else None
        if arguments:
            candidate = arguments[-1]
    return candidate if type(candidate) is exp.Cast and _timezone_owner(candidate) is node else None


def _canonical_type(source: str, node: object) -> bool:
    if any(_catalog_type(node, name) for name in _UNBOUNDED_TYPES):
        return True
    return (
        isinstance(node, exp.DataType)
        and _catalog_type(node, "varchar", bounded=True)
        and (span := _type_range(source, node)) is not None
        and _varchar_bound(source, span) is not None
    )


def _arguments(node: exp.Expr) -> Mapping[str, object]:
    return node.args


def _expression_children(node: exp.Expr, name: str = "expressions") -> tuple[exp.Expr, ...] | None:
    value = _arguments(node).get(name)
    if value is None:
        return ()
    if not _is_object_list(value):
        return None
    expressions: list[exp.Expr] = []
    for item in value:
        if not isinstance(item, exp.Expr):
            return None
        expressions.append(item)
    return tuple(expressions)


def _is_object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _metadata(node: exp.Expr) -> Mapping[str, object]:
    return node.meta


def _timezone_ranges(source: str) -> dict[int, _Range]:
    return {
        match.start("literal"): _Range(match.start(), match.end())
        for pattern in _TIMEZONE_FORMS
        for match in pattern.finditer(source)
    }


def _literal_edit(
    source: str, cast: exp.Cast, positions: Sequence[int], timezones: Mapping[int, _Range], *, rule_id: RuleId
) -> TextEdit | None:
    literal = _arguments(cast).get("this")
    if not isinstance(literal, exp.Literal) or (value := _plain_literal(source, literal)) is None:
        return None
    datatype = _arguments(cast).get("to")
    if not isinstance(datatype, exp.DataType) or (span := _type_range(source, datatype)) is None:
        return None
    index = bisect_left(positions, span.start)
    if index == len(positions) or positions[index] >= span.end:
        return None
    match rule_id:
        case "prefer-text-over-varchar":
            return _text_edit(source, cast, datatype, span, value)
        case "prefer-jsonb":
            return _json_edit(cast, datatype, span, value)
        case "enforce-timestamptz":
            return _timestamp_edit(cast, datatype, literal, value, timezones)
        case _:
            return None


def _text_edit(source: str, cast: exp.Cast, datatype: exp.DataType, span: _Range, value: str) -> TextEdit | None:
    outer = _parent(cast)
    if (
        not _catalog_type(datatype, "varchar", bounded=True)
        or not isinstance(outer, exp.Cast)
        or _arguments(outer).get("this") is not _group(cast)
    ):
        return None
    if not _catalog_type(_arguments(outer).get("to"), "text"):
        return None
    return (
        TextEdit(span.start, span.end, "pg_catalog.text")
        if (bound := _varchar_bound(source, span)) is not None and len(value) <= bound
        else None
    )


def _varchar_bound(source: str, span: _Range) -> int | None:
    match = _TYPE.fullmatch(source[span.start : span.end])
    raw_bound = None if match is None else match.group("bound")
    if raw_bound is None or len(raw_bound) > _MAX_BOUND_DIGITS:
        return None
    bound = int(raw_bound)
    return bound if 0 < bound <= _MAX_VARCHAR_BOUND else None


def _json_edit(cast: exp.Cast, datatype: exp.DataType, span: _Range, value: str) -> TextEdit | None:
    outer = _parent(cast)
    if value not in {"{}", "[]"} or not _catalog_type(datatype, "json") or not isinstance(outer, exp.Cast):
        return None
    if _arguments(outer).get("this") is not _group(cast) or not _catalog_type(_arguments(outer).get("to"), "jsonb"):
        return None
    default = _parent(outer)
    column = default.find_ancestor(exp.ColumnDef) if isinstance(default, exp.DefaultColumnConstraint) else None
    if column is None or not _catalog_type(_arguments(column).get("kind"), "jsonb"):
        return None
    return TextEdit(span.start, span.end, "pg_catalog.jsonb")


def _timestamp_edit(
    cast: exp.Cast, datatype: exp.DataType, literal: exp.Literal, value: str, timezones: Mapping[int, _Range]
) -> TextEdit | None:
    if not _catalog_type(datatype, "timestamp") or not _valid_iso_timestamp(value):
        return None
    owner = _timezone_owner(cast)
    if owner is None or not _named_instant_owner(owner):
        return None
    start = _metadata(literal).get("start")
    if isinstance(start, int) and (span := timezones.get(start)) is not None and _owns_expression(owner, span.start):
        return TextEdit(span.start, span.end, f"CAST('{value}+00' AS pg_catalog.timestamptz)")
    return None


def _plain_literal(source: str, literal: exp.Literal) -> str | None:
    start, end = _metadata(literal).get("start"), _metadata(literal).get("end")
    if not literal.is_string or not isinstance(start, int) or not isinstance(end, int):
        return None
    raw = source[start : end + 1]
    return (
        raw[1:-1] if _PLAIN_STRING.fullmatch(raw) is not None and raw[1:-1] == _arguments(literal).get("this") else None
    )


def _type_range(source: str, datatype: exp.DataType) -> _Range | None:
    kind = _arguments(datatype).get("kind")
    namespace = _arguments(kind).get("this") if isinstance(kind, exp.Dot) else None
    if not isinstance(namespace, exp.Identifier):
        return None
    start = _metadata(namespace).get("start")
    if not isinstance(start, int) or (match := _TYPE.match(source, start)) is None:
        return None
    if not _catalog_type(datatype, match.group("name").lower(), bounded=match.group("bound") is not None):
        return None
    return _Range(start, match.end())


def _catalog_type(node: object, name: str, *, bounded: bool = False) -> bool:
    if not isinstance(node, exp.DataType):
        return False
    arguments = _expression_children(node)
    if arguments is None or bool(arguments) != bounded:
        return False
    kind = _arguments(node).get("kind")
    if not isinstance(kind, exp.Dot):
        return False
    namespace = _arguments(kind).get("this")
    identifier = _arguments(kind).get("expression")
    if (
        not isinstance(namespace, exp.Identifier)
        or not isinstance(identifier, exp.Identifier)
        or namespace.quoted
        or identifier.quoted
    ):
        return False
    return namespace.name.lower() == "pg_catalog" and identifier.name.lower() == name


def _parent(node: exp.Expr) -> exp.Expr | None:
    return _group(node).parent


def _group(node: exp.Expr) -> exp.Expr:
    while isinstance(node.parent, exp.Paren) and _arguments(node.parent).get("this") is node:
        node = node.parent
    return node


def _valid_iso_timestamp(value: str) -> bool:
    if re.fullmatch(_ISO_TIMESTAMP, value) is None:
        return False
    try:
        date.fromisoformat(value[:10])
    except ValueError:
        return False
    return (
        int(value[11:13]) < _HOURS_PER_DAY
        and int(value[14:16]) < _MINUTES_PER_HOUR
        and int(value[17:19]) < _SECONDS_PER_MINUTE
    )


def _timezone_owner(cast: exp.Cast) -> exp.Expr | None:
    parent = _parent(cast)
    if isinstance(parent, exp.AtTimeZone):
        return (
            parent
            if _arguments(parent).get("this") is _group(cast) and _zero_interval(_arguments(parent).get("zone"))
            else None
        )
    if not isinstance(parent, exp.Anonymous) or parent.name.lower() != "timezone":
        return None
    arguments = _expression_children(parent)
    if arguments is None or len(arguments) != _TIMEZONE_ARGUMENT_COUNT:
        return None
    namespace = parent.parent
    identifier = _arguments(namespace).get("this") if isinstance(namespace, exp.Dot) else None
    if not isinstance(identifier, exp.Identifier) or identifier.quoted or identifier.name.lower() != "pg_catalog":
        return None
    return namespace if _zero_interval(arguments[0]) and arguments[1] is _group(cast) else None


def _zero_interval(node: object) -> bool:
    if not isinstance(node, exp.Interval):
        return False
    literal = _arguments(node).get("this")
    return (
        isinstance(literal, exp.Literal)
        and literal.is_string
        and _arguments(literal).get("this") == "00:00"
        and _arguments(node).get("unit") is None
    )


def _named_instant_owner(owner: exp.Expr) -> bool:
    parent = _parent(owner)
    if isinstance(parent, exp.Alias):
        select = parent.parent
        projections = _expression_children(select) if isinstance(select, exp.Select) else None
        return projections is not None and any(item is parent for item in projections)
    column = parent.find_ancestor(exp.ColumnDef) if isinstance(parent, exp.DefaultColumnConstraint) else None
    return column is not None and _catalog_type(_arguments(column).get("kind"), "timestamptz")


def _owns_expression(owner: exp.Expr, start: int) -> bool:
    operand = _arguments(owner).get("this")
    if isinstance(owner, exp.Dot):
        return isinstance(operand, exp.Identifier) and _metadata(operand).get("start") == start
    # The AT TIME ZONE form starts at CAST, before its literal/type leaves.
    return isinstance(owner, exp.AtTimeZone) and isinstance(operand, exp.Cast)
