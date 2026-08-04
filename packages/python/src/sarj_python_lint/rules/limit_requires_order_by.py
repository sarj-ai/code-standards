"""SARJ095 — A row-limited SELECT needs a deterministic result order.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_limit_requires_order_by.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, Severity, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._sql import (
    has_top_level_phrase,
    is_store_module,
    sql_string_value,
    strip_sql_noise,
)


if TYPE_CHECKING:
    from pathlib import Path


_SELECT = re.compile(r"\bSELECT\b[\s\S]*?\bFROM\b", re.IGNORECASE)


class LimitRequiresOrderBy(Rule):
    id: str = "limit-requires-order-by"
    code: str = "SARJ095"
    description: str = "Multi-row SELECT with LIMIT / FETCH but no result-level ORDER BY is unstable."

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
            limited = (
                has_top_level_phrase(sql, "LIMIT")
                or has_top_level_phrase(sql, "FETCH", "FIRST")
                or has_top_level_phrase(sql, "FETCH", "NEXT")
            )
            if not limited or _SELECT.search(sql) is None or has_top_level_phrase(sql, "ORDER", "BY"):
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        "Row-limited SELECT has no result-level ORDER BY, so the chosen rows are unstable — "
                        "order by a deterministic key. Suppress with `# sarj-noqa: SARJ095`."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags
