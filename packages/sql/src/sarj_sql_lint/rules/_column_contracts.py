from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

from sqlglot import exp
from sqlglot.errors import SqlglotError

from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.rule_base import dollar_quoted_spans, mask_sql, normalize_sql_identifier
from sarj_sql_lint.rules._copy_input import sql_before_copy_input


if TYPE_CHECKING:
    from collections.abc import Iterator


_CREATE_TABLE = re.compile(
    r"^\s*CREATE\s+(?:(?:GLOBAL|LOCAL)\s+)?(?:(?:TEMP(?:ORARY)?|UNLOGGED)\s+)?TABLE\b", re.IGNORECASE
)
_NON_NEWLINE = re.compile(r"[^\r\n]")


@dataclass(frozen=True, slots=True)
class TableContract:
    schema: exp.Schema
    offset: int

    @property
    def columns(self) -> tuple[exp.ColumnDef, ...]:
        return tuple(item for item in self.schema.iter_expressions() if isinstance(item, exp.ColumnDef))

    @property
    def checks(self) -> tuple[exp.Expr, ...]:
        return tuple(
            expression
            for check in self.schema.find_all(exp.CheckColumnConstraint)
            if (expression := child(check, "this")) is not None
        )


def table_contracts(source: str) -> Iterator[TableContract]:
    source = sql_before_copy_input(source)
    masked = mask_sql(source, mask_dollar_literals=True)
    for start, end in dollar_quoted_spans(source):
        masked = masked[:start] + _NON_NEWLINE.sub(" ", masked[start:end]) + masked[end:]
    start = 0
    for separator in (*[match.start() for match in re.finditer(r";", masked)], len(masked)):
        if _CREATE_TABLE.match(masked[start:separator]) is not None:
            try:
                statements = parse_postgres(source[start:separator])
            except SqlglotError, RecursionError:
                statements = []
            for statement in statements:
                if isinstance(statement, exp.Create) and isinstance(schema := child(statement, "this"), exp.Schema):
                    yield TableContract(schema, start)
        start = separator + 1


def column_key(column: exp.Column | exp.ColumnDef) -> str:
    identifier = child(column, "this")
    return normalize_sql_identifier(identifier.sql(dialect="postgres")) if identifier is not None else ""


def child(node: exp.Expr, key: str) -> exp.Expr | None:
    return next((item for item in node.iter_expressions() if item.arg_key == key), None)


def column_offset(column: exp.ColumnDef) -> int:
    identifier = child(column, "this")
    if identifier is not None and isinstance(offset := identifier.meta.get("start"), int):
        return offset
    return 0


def bare_column(node: exp.Expr, name: str) -> bool:
    return isinstance(node, exp.Column) and not node.table and column_key(node) == name


def unparenthesize(node: exp.Expr) -> exp.Expr:
    while isinstance(node, exp.Paren):
        value = child(node, "this")
        if value is None:
            break
        node = value
    return node
