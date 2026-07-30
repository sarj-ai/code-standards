"""SARJ019: a SQL query with 3+ JOINs is too entangled — split or denormalize.

Three years of store reviews repeatedly push back on multi-table joins inside a
single store query ("can we remove the joins?", "do the join at the application
layer", "whenever I see a join my ears perk up"). A query fanning across many
tables couples models that should stay separate, is hard to index well, and
usually wants either denormalization or splitting into per-store reads joined in
application code.

This rule walks SQL string literals embedded in `.py` (the raw queries in
`*_store.py`) and flags any single query string containing **3 or more** `JOIN`
keywords. `LEFT/RIGHT/INNER/FULL/CROSS JOIN` each count as one. SQL string-literal
values and `--` / `/* */` comments are neutralized first, so a `'join'` value or
a `--` inside a quoted value never affects the count. Only strings that actually
look like a query (they contain a `FROM`) are considered, keeping false positives
low.

If a join-heavy read is genuinely the right call, suppress with
`# sarj-noqa: SARJ019 — <reason>`.
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

_MAX_JOINS = 2


class NoQueryWithManyJoins(Rule):
    """A SQL query with 3+ JOINs is too entangled — split it or denormalize."""

    id: str = "no-query-with-many-joins"
    code: str = "SARJ019"
    description: str = (
        "SQL query with 3 or more JOINs — split the query or denormalize instead of fanning across many tables."
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
            join_count = len(_JOIN.findall(sql))
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
