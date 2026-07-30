"""SARJ021: no `SELECT *` in a store query — list the columns you need.

`SELECT *` over-fetches: it pulls every column (including large JSONB / text
blobs the caller never reads), breaks `class_row(Model)` mapping the moment a
column is added or reordered, and hides which columns a query actually depends
on. The recurring review ask is to name the columns explicitly.

This rule walks SQL string literals embedded in `.py` (`*_store.py`) and flags
any query (a string containing `FROM`) whose projection list holds a `*` in any
position — bare (`SELECT *`, `SELECT id, *`), qualified (`c.*`, `public.call.*`),
or after `DISTINCT ON (...)`. SQL string-literal values and `--` / `/* */`
comments are neutralized first, so a `'*'` value is never mistaken for a star.
`COUNT(*)` is NOT flagged (the star is a function argument, not a projection),
`a * b` arithmetic is NOT flagged, and `EXISTS (SELECT * ...)` is exempt (the
columns are unused).

    # flagged
    "SELECT * FROM call WHERE id = %s"
    "SELECT c.* FROM call c"

    # preferred
    "SELECT id, status, created_at FROM call WHERE id = %s"

Suppress a deliberate case with `# sarj-noqa: SARJ021 — <reason>`.
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


# A real SQL query shape, so prose strings with the bare word "from" aren't matched.
_QUERY_SHAPE = re.compile(r"\bSELECT\b[\s\S]*?\bFROM\b", re.IGNORECASE)
_SELECT_KW = re.compile(r"\bSELECT\b", re.IGNORECASE)
_FROM_KW = re.compile(r"FROM\b", re.IGNORECASE)
_EXISTS_BEFORE = re.compile(r"\bEXISTS\s*\(\s*$", re.IGNORECASE)
# A `word.` immediately preceding a `*` marks a qualified star (`c.*`, `public.call.*`).
_QUALIFIED_PREFIX = re.compile(r"\w\.$")


def _is_projection_star(sql: str, pos: int) -> bool:
    """Report whether the `*` at `pos` is a column-projection star.

    A projection star expands columns: bare (`SELECT *`, `id, *`), qualified
    (`c.*`, `public.call.*`), or after `DISTINCT ON (...)`. It is NOT a
    `COUNT(*)` argument (`(*)`) nor an `a * b` multiply (an operand follows).

    Returns:
        True when the `*` at `pos` projects columns.

    """
    if _QUALIFIED_PREFIX.search(sql[:pos]) is not None:
        return True
    before = pos - 1
    while before >= 0 and sql[before].isspace():
        before -= 1
    after = pos + 1
    while after < len(sql) and sql[after].isspace():
        after += 1
    before_char = sql[before] if before >= 0 else ""
    after_char = sql[after] if after < len(sql) else ""
    terminates = after_char in {"", ",", ")"} or _FROM_KW.match(sql, after) is not None
    if not terminates:
        return False
    return not (before_char == "(" and after_char == ")")


def _has_real_select_star(sql: str) -> bool:
    selects = [m.start() for m in _SELECT_KW.finditer(sql)]
    for pos, ch in enumerate(sql):
        if ch != "*" or not _is_projection_star(sql, pos):
            continue
        owning = max((s for s in selects if s < pos), default=None)
        if owning is not None and _EXISTS_BEFORE.search(sql[:owning]) is None:
            return True
    return False


class NoSelectStar(Rule):
    """`SELECT *` in a store query — list the columns explicitly."""

    id: str = "no-select-star"
    code: str = "SARJ021"
    description: str = (
        "SELECT * in a store query — name the columns; * over-fetches and breaks "
        "class_row mapping when the schema changes."
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
            if _QUERY_SHAPE.search(sql) is None or not _has_real_select_star(sql):
                continue

            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        "Store query uses SELECT * — list the columns explicitly "
                        "(* over-fetches and breaks class_row mapping). Suppress "
                        "with `# sarj-noqa: SARJ021`."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags
