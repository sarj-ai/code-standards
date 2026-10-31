from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sarj_rule_contracts import TextEdit, apply_edits
from sqlglot import exp
from sqlglot.errors import SqlglotError

from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.rule_base import POSTGRES_IDENTIFIER_PART, sql_comments, sql_relation_key
from sarj_sql_lint.rules._index_analysis import parse_indexes
from sarj_sql_lint.rules.invalid_postgres_ddl import InvalidPostgresDdl


if TYPE_CHECKING:
    from pathlib import Path


_LIMIT = 8192
_HEADER = re.compile(
    rf"\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?"
    rf"(?:IF\s+NOT\s+EXISTS\s+)?(?P<prefix>(?P<schema>{POSTGRES_IDENTIFIER_PART})\s*\.\s*)"
    rf"(?P<name>{POSTGRES_IDENTIFIER_PART})\s+ON\s+"
    rf"(?P<table_schema>{POSTGRES_IDENTIFIER_PART})\s*\.\s*"
    rf"(?P<table_name>{POSTGRES_IDENTIFIER_PART})(?=\s|\()",
    re.IGNORECASE,
)


def repair_index_name(path: Path, source: str) -> str:
    if len(source) > _LIMIT:
        return source
    match = _HEADER.match(source)
    if match is None or sql_relation_key(match["schema"]) != sql_relation_key(match["table_schema"]):
        return source
    if sql_comments(source, mask_dollar_literals=True):
        return source
    if not InvalidPostgresDdl().check(path, source):
        return source
    prefix = match["prefix"]
    preserved_lines = "".join(re.findall(r"\r\n|\r|\n", prefix))
    candidate = apply_edits(source, [TextEdit(match.start("prefix"), match.end("prefix"), preserved_lines)])
    if not _same_index_contract(source, candidate, name=match["name"]):
        return source
    return (
        candidate
        if _supported_index(candidate, match=match) and not InvalidPostgresDdl().check(path, candidate)
        else source
    )


def _same_index_contract(source: str, candidate: str, *, name: str) -> bool:
    before = parse_indexes(source)
    after = parse_indexes(candidate)
    return (
        len(before) == len(after) == 1
        and before[0].signature == after[0].signature
        and sql_relation_key(after[0].name) == sql_relation_key(name)
    )


def _supported_index(source: str, *, match: re.Match[str]) -> bool:
    try:
        statements = parse_postgres(source)
    except SqlglotError, RecursionError:
        return False
    if len(statements) != 1 or not isinstance(statement := statements[0], exp.Create):
        return False
    if statement.args.get("kind") != "INDEX" or statement.find(exp.Command) is not None:
        return False
    index = _child(statement, "this")
    if not isinstance(index, exp.Index):
        return False
    name = _child(index, "this")
    table = _child(index, "table")
    if not isinstance(name, exp.Identifier) or not isinstance(table, exp.Table):
        return False
    schema = _child(table, "db")
    relation = _child(table, "this")
    return (
        _child(table, "catalog") is None
        and isinstance(schema, exp.Identifier)
        and isinstance(relation, exp.Identifier)
        and sql_relation_key(name.sql(dialect="postgres")) == sql_relation_key(match["name"])
        and sql_relation_key(schema.sql(dialect="postgres")) == sql_relation_key(match["table_schema"])
        and sql_relation_key(relation.sql(dialect="postgres")) == sql_relation_key(match["table_name"])
    )


def _child(node: exp.Expr, key: str) -> exp.Expr | None:
    return next((child for child in node.iter_expressions() if child.arg_key == key), None)
