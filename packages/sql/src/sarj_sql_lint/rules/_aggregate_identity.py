from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from types import MappingProxyType
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from sqlglot import exp
    from sqlglot.tokenizer_core import Token


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")
_POSTGRES_AGGREGATES = frozenset(
    {
        "ANY_VALUE",
        "ARRAY_AGG",
        "AVG",
        "BIT_AND",
        "BIT_OR",
        "BIT_XOR",
        "BOOL_AND",
        "BOOL_OR",
        "COUNT",
        "EVERY",
        "JSON_AGG",
        "JSONB_AGG",
        "JSON_AGG_STRICT",
        "JSONB_AGG_STRICT",
        "JSON_ARRAYAGG",
        "JSON_OBJECTAGG",
        "JSON_OBJECT_AGG",
        "JSONB_OBJECT_AGG",
        "JSON_OBJECT_AGG_STRICT",
        "JSONB_OBJECT_AGG_STRICT",
        "JSON_OBJECT_AGG_UNIQUE",
        "JSONB_OBJECT_AGG_UNIQUE",
        "JSON_OBJECT_AGG_UNIQUE_STRICT",
        "JSONB_OBJECT_AGG_UNIQUE_STRICT",
        "MAX",
        "MIN",
        "RANGE_AGG",
        "RANGE_INTERSECT_AGG",
        "STRING_AGG",
        "SUM",
        "XMLAGG",
        "CORR",
        "COVAR_POP",
        "COVAR_SAMP",
        "REGR_AVGX",
        "REGR_AVGY",
        "REGR_COUNT",
        "REGR_INTERCEPT",
        "REGR_R2",
        "REGR_SLOPE",
        "REGR_SXX",
        "REGR_SXY",
        "REGR_SYY",
        "STDDEV",
        "STDDEV_POP",
        "STDDEV_SAMP",
        "VARIANCE",
        "VAR_POP",
        "VAR_SAMP",
        "MODE",
        "PERCENTILE_CONT",
        "PERCENTILE_DISC",
        "RANK",
        "DENSE_RANK",
        "PERCENT_RANK",
        "CUME_DIST",
    }
)
_BUILTINS = MappingProxyType(
    {
        "postgres": _POSTGRES_AGGREGATES,
        "sqlite": frozenset(
            {
                "AVG",
                "COUNT",
                "GROUP_CONCAT",
                "MAX",
                "MEDIAN",
                "MIN",
                "PERCENTILE",
                "PERCENTILE_CONT",
                "PERCENTILE_DISC",
                "STRING_AGG",
                "SUM",
                "TOTAL",
                "JSON_GROUP_ARRAY",
                "JSON_GROUP_OBJECT",
                "JSONB_GROUP_ARRAY",
                "JSONB_GROUP_OBJECT",
            }
        ),
        "mysql": frozenset(
            {
                "AVG",
                "BIT_AND",
                "BIT_OR",
                "BIT_XOR",
                "COUNT",
                "GROUP_CONCAT",
                "JSON_ARRAYAGG",
                "JSON_OBJECTAGG",
                "MAX",
                "MIN",
                "STD",
                "STDDEV",
                "STDDEV_POP",
                "STDDEV_SAMP",
                "SUM",
                "VAR_POP",
                "VAR_SAMP",
                "VARIANCE",
            }
        ),
    }
)
_AGGREGATE_NAMES = frozenset(name for names in _BUILTINS.values() for name in names)
_SQL_WORDS = re.compile(r"\w+")
_CLASS_ALIASES = MappingProxyType(
    {
        "GroupConcat": frozenset({"GROUP_CONCAT", "STRING_AGG"}),
        "JSONArrayAgg": frozenset({"JSON_AGG", "JSONB_AGG", "JSON_ARRAYAGG", "JSON_GROUP_ARRAY", "JSONB_GROUP_ARRAY"}),
        "JSONObjectAgg": frozenset({"JSON_OBJECTAGG", "JSON_GROUP_OBJECT", "JSONB_GROUP_OBJECT"}),
        "JSONBObjectAgg": frozenset({"JSONB_OBJECT_AGG"}),
    }
)
_HYPOTHETICAL = frozenset({"RANK", "DENSE_RANK", "PERCENT_RANK", "CUME_DIST"})


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _SourceCall:
    name: str
    quoted: bool
    name_start: int
    name_end: int
    arguments_start: int
    end: int
    statement_start: int

    @property
    def key(self) -> str:
        return self.name.upper()


def contains_aggregate_spelling(sql: str) -> bool:
    # A lexical precheck may overmatch values/comments; parsed native identity still decides.
    return not _AGGREGATE_NAMES.isdisjoint(_SQL_WORDS.findall(sql.upper()))


def aggregate_name(node: exp.Expr, sql: str, dialect: str) -> str | None:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- only SQL candidates need the parser.

    dialect = {"postgresql": "postgres", "mariadb": "mysql"}.get(dialect, dialect)
    builtins = _BUILTINS.get(dialect)
    if builtins is None or not isinstance(node, exp.AggFunc | exp.Anonymous):
        return None
    if isinstance(node, exp.Anonymous) and node.name.upper() not in builtins:
        return None
    if not _schema_allowed(node, dialect):
        return None
    call = _source_call(node, sql, dialect)
    if call is None or (dialect == "postgres" and call.quoted and call.name != call.name.lower()):
        return None
    name = call.key
    if name not in builtins or _is_scalar(node, name, dialect):
        return None
    if dialect == "postgres" and name in _HYPOTHETICAL and not _within_group(node):
        return None
    return name


def aggregate_offset(node: exp.Expr, sql: str, dialect: str) -> int | None:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- paired with aggregate classification.

    if not isinstance(node, exp.Func):
        return None
    call = _source_call(node, sql, dialect)
    return call.name_start if call is not None else None


def _schema_allowed(node: exp.Expr, dialect: str) -> bool:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- paired with aggregate classification.

    parent = node.parent
    if not isinstance(parent, exp.Dot) or _argument(parent, "expression") is not node:
        return True
    owner = _argument(parent, "this")
    if dialect != "postgres" or not isinstance(owner, exp.Identifier):
        return False
    if owner.quoted:
        return owner.name == "pg_catalog"
    return _IDENTIFIER.fullmatch(owner.name) is not None and owner.name.lower() == "pg_catalog"


def _is_scalar(node: exp.Expr, name: str, dialect: str) -> bool:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- paired with aggregate classification.

    if dialect == "mysql" and name == "ANY_VALUE":
        return True
    if dialect != "sqlite" or name not in {"MIN", "MAX"}:
        return False
    if isinstance(node, exp.Anonymous):
        return len(node.expressions) > 1
    return bool(node.expressions)


def _within_group(node: exp.Expr) -> bool:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- paired with aggregate classification.

    parent = node.parent
    if isinstance(parent, exp.Dot) and _argument(parent, "expression") is node:
        node, parent = parent, parent.parent
    return isinstance(parent, exp.WithinGroup) and _argument(parent, "this") is node


def _argument(node: exp.Expr, name: str) -> exp.Expr | None:
    return next((child for child in node.iter_expressions() if child.arg_key == name), None)


def _source_call(node: exp.Func, sql: str, dialect: str) -> _SourceCall | None:
    calls = _source_calls(sql, dialect)
    span = _span(node)
    if span is not None:
        return next((call for call in calls if call.name_start == span.start and call.name_end == span.end), None)
    return _call_without_metadata(node, calls)


def _call_without_metadata(node: exp.Func, calls: tuple[_SourceCall, ...]) -> _SourceCall | None:
    names = _function_names(node)
    candidates = [call for call in calls if call.key in names]
    spans = [span for child in node.walk() if (span := _span(child)) is not None]
    if not spans:
        return _unpositioned_call(node, calls, names)
    first, last = min(span.start for span in spans), max(span.end for span in spans)
    containing = [call for call in candidates if call.arguments_start <= first and last < call.end]
    depth = _matching_ancestors(node, names)
    return containing[depth] if len(containing) > depth else None


def _unpositioned_call(node: exp.Func, calls: tuple[_SourceCall, ...], names: frozenset[str]) -> _SourceCall | None:
    root = node.root()
    statement_start = _containing_statement_start(root, calls)
    if statement_start is None:
        return None
    candidates = [call for call in calls if call.statement_start == statement_start and call.key in names]
    functions = [
        function for function in _source_ordered_functions(root) if not names.isdisjoint(_function_names(function))
    ]
    if len(functions) != len(candidates):
        return None
    return next((call for function, call in zip(functions, candidates, strict=True) if function is node), None)


def _containing_statement_start(root: exp.Expr, calls: tuple[_SourceCall, ...]) -> int | None:
    starts = {call.statement_start for call in calls}
    first = min((span.start for child in root.walk() if (span := _span(child)) is not None), default=None)
    if first is not None:
        return max((start for start in starts if start <= first), default=None)
    return next(iter(starts)) if len(starts) == 1 else None


def _source_ordered_functions(root: exp.Expr) -> list[exp.Func]:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- paired with source-call recovery.

    functions: list[exp.Func] = []
    pending = [root]
    while pending:
        current = pending.pop()
        if isinstance(current, exp.Func):
            functions.append(current)
        children = list(current.iter_expressions())
        # WITH is attached after the main query; SELECT stores LIMIT before FROM.
        # Keep all functions, including quoted and schema-owned calls, as alignment slots.
        order = {"with_": -1, "limit": 1, "offset": 2, "locks": 3} if isinstance(current, exp.Select) else {"with_": -1}
        children.sort(key=lambda child: order.get(child.arg_key or "", 0))
        pending.extend(reversed(children))
    return functions


def _matching_ancestors(node: exp.Expr, names: frozenset[str]) -> int:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- paired with source-call recovery.

    count = 0
    current = node.parent
    while current is not None:
        if isinstance(current, exp.Func) and not names.isdisjoint(_function_names(current)):
            count += 1
        current = current.parent
    return count


def _function_names(node: exp.Func) -> frozenset[str]:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- paired with source-call recovery.

    if isinstance(node, exp.Anonymous):
        return frozenset({node.name.upper()})
    return _CLASS_ALIASES.get(type(node).__name__, frozenset(node.sql_names()))


def _span(node: exp.Expr) -> _Span | None:
    start = node.meta.get("start")
    end = node.meta.get("end")
    if isinstance(start, int) and isinstance(end, int) and 0 <= start <= end:
        return _Span(start, end)
    return None


@lru_cache(maxsize=16)
def _source_calls(sql: str, dialect: str) -> tuple[_SourceCall, ...]:
    import sqlglot  # ruff: ignore[import-outside-top-level] -- preserve original quoted function identities.
    from sqlglot.errors import SqlglotError  # ruff: ignore[import-outside-top-level] -- paired with the tokenizer.
    from sqlglot.tokenizer_core import TokenType  # ruff: ignore[import-outside-top-level] -- quoted text must not supply parentheses.

    try:
        tokens = sqlglot.tokenize(sql, read=dialect)
    except SqlglotError, RecursionError:
        return ()
    stack: list[int] = []
    calls: list[_SourceCall] = []
    statement_start = 0
    for index, token in enumerate(tokens):
        if token.token_type is TokenType.SEMICOLON:
            statement_start = token.end + 1
        if token.token_type is TokenType.L_PAREN:
            stack.append(index)
        elif token.token_type is TokenType.R_PAREN and stack:
            opening = stack.pop()
            if (call := _call_at(tokens, opening, token.end, sql, statement_start)) is not None:
                calls.append(call)
    return tuple(sorted(calls, key=lambda call: call.name_start))


def _call_at(tokens: list[Token], opening: int, end: int, sql: str, statement_start: int) -> _SourceCall | None:
    if opening == 0:
        return None
    token = tokens[opening - 1]
    raw = sql[token.start : token.end + 1]
    quoted = (raw[:1], raw[-1:]) in {('"', '"'), ("`", "`"), ("[", "]")}
    if quoted:
        closing = raw[-1]
        raw = raw[1:-1].replace(closing * 2, closing)
    if _IDENTIFIER.fullmatch(raw) is None:
        return None
    return _SourceCall(raw, quoted, token.start, token.end, tokens[opening].end + 1, end, statement_start)
