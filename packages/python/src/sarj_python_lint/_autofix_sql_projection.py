from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
import re
from typing import TYPE_CHECKING

from sarj_rule_contracts import TextEdit, apply_edits
from sqlglot import exp, parse_one
from sqlglot.errors import ParseError, TokenError

from sarj_python_lint._closed_sql_literal import (
    has_comments as _has_comments,
    literal_query as _literal_query,
    owned_literal as _owned_literal,
)
from sarj_python_lint.rules._ast_index import object_list
from sarj_python_lint.rules._store_sql import sql_child, sql_children
from sarj_python_lint.rules.no_redundant_sql_alias import identifier_key


if TYPE_CHECKING:
    import ast

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic


_QUERY = re.compile(
    r"[ \t]*SELECT[ \t]+(?P<star>\*)[ \t]+FROM[ \t]+"
    r"\([ \t]*VALUES[ \t]+\([ \t]*(?P<values>[0-9]{1,9}(?:[ \t]*,[ \t]*[0-9]{1,9}){0,7})"
    r'[ \t]*\)[ \t]*\)[ \t]+AS[ \t]+(?P<alias>"[A-Za-z_][A-Za-z0-9_]{0,62}")[ \t]*'
    r'\([ \t]*(?P<labels>"[A-Za-z_][A-Za-z0-9_]{0,62}"'
    r'(?:[ \t]*,[ \t]*"[A-Za-z_][A-Za-z0-9_]{0,62}"){0,7})[ \t]*\)'
    r"[ \t]*;?[ \t]*\Z",
    re.IGNORECASE | re.ASCII,
)
_QUERY_LIMIT = 2048
_SQL_IDENTIFIER = r'(?:"[A-Za-z_][A-Za-z0-9_]{0,62}"|[A-Za-z_][A-Za-z0-9_]{0,62})'
_INTEGER_LITERAL = re.compile(r"[0-9]{1,9}\Z", re.ASCII)
_VALUES_ROW = r"\([ \t]*[0-9]{1,9}(?:[ \t]*,[ \t]*[0-9]{1,9}){0,7}[ \t]*\)"
_VALUES_BOUND = 8
_SELF_ALIAS_COLUMN = re.compile(
    rf"(?P<column>{_SQL_IDENTIFIER}\.{_SQL_IDENTIFIER})(?P<alias>[ \t]+AS[ \t]+{_SQL_IDENTIFIER})?",
    re.IGNORECASE | re.ASCII,
)
_SELF_ALIAS_QUERY = re.compile(
    rf"[ \t]*SELECT[ \t]+(?P<columns>{_SELF_ALIAS_COLUMN.pattern}"
    rf"(?:[ \t]*,[ \t]*{_SQL_IDENTIFIER}\.{_SQL_IDENTIFIER}(?:[ \t]+AS[ \t]+{_SQL_IDENTIFIER})?){{0,7}})"
    r"[ \t]+FROM[ \t]+\([ \t]*VALUES[ \t]+"
    rf"{_VALUES_ROW}(?:[ \t]*,[ \t]*{_VALUES_ROW}){{0,7}}[ \t]*\)"
    rf"[ \t]+AS[ \t]+{_SQL_IDENTIFIER}[ \t]*\([ \t]*"
    rf"{_SQL_IDENTIFIER}(?:[ \t]*,[ \t]*{_SQL_IDENTIFIER}){{0,7}}[ \t]*\)[ \t]*;?[ \t]*\Z",
    re.IGNORECASE | re.ASCII,
)


@dataclass(frozen=True, slots=True)
class _Projection:
    offset: int
    replacement: str


def fixes(context: PythonFileContext, diagnostic: Diagnostic) -> list[TextEdit]:
    tree = context.tree
    if tree is None or context.generated or _has_comments(context.source):
        return []
    literal = _owned_literal(tree)
    if literal is None or (literal.lineno, literal.col_offset + 1) != (diagnostic.line, diagnostic.col):
        return []
    query = _literal_query(context.source, literal)
    projection = _projection(query) if query is not None else None
    if projection is None:
        return []
    start = _literal_offset(context.source, literal) + projection.offset
    return [TextEdit(start, start + 1, projection.replacement)]


def alias_fixes(context: PythonFileContext, diagnostic: Diagnostic) -> list[TextEdit]:
    tree = context.tree
    if tree is None or context.generated or _has_comments(context.source):
        return []
    literal = _owned_literal(tree)
    if literal is None or (literal.lineno, literal.col_offset + 1) != (diagnostic.line, diagnostic.col):
        return []
    query = _literal_query(context.source, literal)
    if query is None:
        return []
    start = _literal_offset(context.source, literal)
    return [TextEdit(start + edit.start, start + edit.end, edit.replacement) for edit in _alias_edits(query)]


def _literal_offset(source: str, literal: ast.Constant) -> int:
    lines = StringIO(source, newline="").readlines()
    prefix = lines[literal.lineno - 1].encode("utf-8")[: literal.col_offset].decode("utf-8")
    return sum(map(len, lines[: literal.lineno - 1])) + len(prefix) + 1


def _alias_edits(query: str) -> list[TextEdit]:
    if len(query) > _QUERY_LIMIT or (matched := _SELF_ALIAS_QUERY.fullmatch(query)) is None:
        return []
    offset = matched.start("columns")
    edits = [
        TextEdit(offset + part.start("alias"), offset + part.end("alias"), "")
        for part in _SELF_ALIAS_COLUMN.finditer(matched["columns"])
        if part.group("alias") is not None
    ]
    if not edits:
        return []
    candidate = apply_edits(query, edits)
    return edits if _alias_delta(query, candidate) else []


def _alias_delta(original: str, candidate: str) -> bool:
    try:
        before = parse_one(original, read="postgres")
        after = parse_one(candidate, read="postgres")
    except ParseError, TokenError:
        return False
    if not isinstance(before, exp.Select) or not isinstance(after, exp.Select):
        return False
    columns = _self_alias_columns(before)
    if columns is None:
        return False
    expected = before.copy()
    expected.set("expressions", [part.copy() for part in columns])
    return expected == after


def _self_alias_columns(statement: exp.Select) -> list[exp.Column] | None:
    from_clause = sql_child(statement, "from_")
    relation = sql_child(from_clause, "this") if isinstance(from_clause, exp.From) else None
    alias = sql_child(relation, "alias") if isinstance(relation, exp.Values) else None
    if not isinstance(alias, exp.TableAlias):
        return None
    qualifier = identifier_key(sql_child(alias, "this"))
    labels = [identifier_key(part) for part in sql_children(alias, "columns")]
    if (
        qualifier is None
        or None in labels
        or len(set(labels)) != len(labels)
        or not isinstance(relation, exp.Values)
        or not _literal_rows(relation, len(labels))
    ):
        return None
    columns: list[exp.Column] = []
    for expression in sql_children(statement, "expressions"):
        column = _self_alias_column(expression)
        if (
            column is None
            or identifier_key(sql_child(column, "table")) != qualifier
            or identifier_key(sql_child(column, "this")) not in labels
        ):
            return None
        columns.append(column)
    return columns


def _literal_rows(relation: exp.Values, width: int) -> bool:
    rows = sql_children(relation, "expressions")
    return (
        1 <= width <= _VALUES_BOUND
        and 1 <= len(rows) <= _VALUES_BOUND
        and all(isinstance(row, exp.Tuple) and _literal_row(row, width) for row in rows)
    )


def _literal_row(row: exp.Tuple, width: int) -> bool:
    values = sql_children(row, "expressions")
    return len(values) == width and all(
        isinstance(value, exp.Literal) and not value.is_string and _INTEGER_LITERAL.fullmatch(value.name) is not None
        for value in values
    )


def _self_alias_column(expression: exp.Expr) -> exp.Column | None:
    if isinstance(expression, exp.Column):
        return expression
    column = sql_child(expression, "this") if isinstance(expression, exp.Alias) else None
    if not isinstance(column, exp.Column):
        return None
    original = identifier_key(sql_child(column, "this"))
    return column if original is not None and original == identifier_key(sql_child(expression, "alias")) else None


def _projection(query: str) -> _Projection | None:
    if len(query) > _QUERY_LIMIT or (matched := _QUERY.fullmatch(query)) is None:
        return None
    labels = [part.strip() for part in matched["labels"].split(",")]
    if len(labels) != len(matched["values"].split(",")) or len(set(labels)) != len(labels):
        return None
    replacement = ", ".join(f"{matched['alias']}.{label}" for label in labels)
    candidate = query[: matched.start("star")] + replacement + query[matched.end("star") :]
    if not _projection_delta(query, candidate):
        return None
    return _Projection(offset=matched.start("star"), replacement=replacement)


def _projection_delta(original: str, candidate: str) -> bool:
    try:
        before = parse_one(original, read="postgres")
        after = parse_one(candidate, read="postgres")
    except ParseError, TokenError:
        return False
    if not isinstance(before, exp.Select) or not isinstance(after, exp.Select) or before.expressions != [exp.Star()]:
        return False
    columns = _projection_columns(after.expressions)
    if columns is None:
        return False
    expected = before.copy()
    expected.set("expressions", [part.copy() for part in columns])
    return expected == after


def _projection_columns(value: object) -> list[exp.Column] | None:
    if not object_list(value):
        return None
    columns: list[exp.Column] = []
    for part in value:
        if not isinstance(part, exp.Column):
            return None
        columns.append(part)
    return columns
