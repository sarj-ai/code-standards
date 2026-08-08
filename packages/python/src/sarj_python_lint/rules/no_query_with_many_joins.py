"""SARJ019 — A SQL query with 3+ join operations is too entangled.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_query_with_many_joins.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._sql import is_store_module, sql_string_value, strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path


# A real query shape, so prose with the bare words "from"/"join" isn't matched.
_QUERY_SHAPE = re.compile(
    r"\bSELECT\b[\s\S]*?\bFROM\b|\bUPDATE\b[\s\S]*?\bSET\b|\bDELETE\b\s+FROM\b",
    re.IGNORECASE,
)
_JOIN = re.compile(r"\bJOIN\b", re.IGNORECASE)
_FROM = re.compile(r"\bFROM\b", re.IGNORECASE)
_FROM_CLAUSE_BOUNDARY = re.compile(
    r"\b(?:WHERE|GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT|OFFSET|FETCH|FOR|"
    r"UNION|INTERSECT|EXCEPT|RETURNING|WINDOW|QUALIFY|ON\s+CONFLICT|SET)\b",
    re.IGNORECASE,
)

_MAX_JOINS = 2


class NoQueryWithManyJoins(Rule):
    id: str = "no-query-with-many-joins"
    code: str = "SARJ019"
    description: str = (
        "SQL query with 3 or more explicit or implicit joins — split the query or denormalize "
        "instead of fanning across many tables."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_store_module(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags: list[Diagnostic] = []
        consumed: set[int] = set()
        for node in nodes(tree, ast.Constant, ast.BinOp):
            if id(node) in consumed:
                continue
            text = sql_string_value(node)
            if text is None:
                continue
            consumed.update(id(sub) for sub in walk(node))

            sql = strip_sql_noise(text)
            if _QUERY_SHAPE.search(sql) is None:
                continue
            join_count = len(_JOIN.findall(sql)) + _implicit_join_count(sql)
            if join_count <= _MAX_JOINS:
                continue

            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"Query has {join_count} JOINs (max {_MAX_JOINS}) — split it "
                        "into separate store reads joined in application code, or "
                        "denormalize. Suppress with `# sarj-noqa: SARJ019`."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _implicit_join_count(sql: str) -> int:
    """Count top-level relation separators in every ``FROM`` clause."""
    depths: list[int] = []
    depth = 0
    for char in sql:
        depths.append(depth)
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1

    count = 0
    for match in _FROM.finditer(sql):
        clause_depth = depths[match.start()]
        i = match.end()
        while i < len(sql):
            if depths[i] < clause_depth:
                break
            if depths[i] == clause_depth:
                if _FROM_CLAUSE_BOUNDARY.match(sql, i):
                    break
                if sql[i] == ",":
                    count += 1
            i += 1
    return count
