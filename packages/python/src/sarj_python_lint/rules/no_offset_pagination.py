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


# Require a shared dialect parameter after `OFFSET`, excluding prose and
# BigQuery's `WITH OFFSET AS` array indexing.
_OFFSET_PAGINATION = re.compile(
    r"\bOFFSET\s+(?:%s|%\(\w+\)s|\?\d*|:\w+|@\w+|\$\d+|(?:0*[1-9]\d*))",
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
        for node in nodes(tree, ast.Constant, ast.BinOp, ast.JoinedStr):
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
