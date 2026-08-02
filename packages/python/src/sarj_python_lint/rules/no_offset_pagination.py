"""SARJ025 — No `OFFSET` pagination in a store query — use a keyset cursor.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_offset_pagination.py
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


# `OFFSET` followed by a value/param token — the real pagination construct. This
# excludes the English word ("no base offset"), `'offset'` dict keys, and BigQuery
# `UNNEST(...) WITH OFFSET AS col` (array indexing, no value token after OFFSET).
#
# The parameter alternatives are the UNION of every marker the three packages
# see, and are kept identical in SARJ107 and the TS twin — see the module
# docstring. `\?\d*` (sqlite3 / aiosqlite / D1) was missing here specifically,
# which made `LIMIT ? OFFSET ?` a silent false negative in Python while the TS
# twin caught it.
_OFFSET_PAGINATION = re.compile(
    r"\bOFFSET\s+(?:%s|%\(\w+\)s|\?\d*|:\w+|@\w+|\$\d+|\d+)",
    re.IGNORECASE,
)


class NoOffsetPagination(Rule):
    id: str = "no-offset-pagination"
    code: str = "SARJ025"
    description: str = (
        "OFFSET pagination is O(N) and unstable under concurrent writes — use a "
        "keyset cursor (WHERE id > :cursor ORDER BY id LIMIT n)."
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
            if _OFFSET_PAGINATION.search(sql) is None:
                continue

            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        "Store query uses OFFSET pagination (O(N), unstable under "
                        "concurrent writes) — use a keyset cursor (WHERE id > :cursor "
                        "ORDER BY id LIMIT n). Suppress with `# sarj-noqa: SARJ025`."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags
