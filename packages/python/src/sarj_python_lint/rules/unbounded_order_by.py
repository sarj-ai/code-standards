"""SARJ096 — Review a result sort that has no database row cap.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_unbounded_order_by.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, Severity, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._sql import (
    has_top_level_phrase,
    has_top_level_row_cap,
    is_store_module,
    sql_string_value,
    strip_sql_noise,
)


if TYPE_CHECKING:
    from pathlib import Path


_SELECT = re.compile(r"\bSELECT\b[\s\S]*?\bFROM\b", re.IGNORECASE)


class UnboundedOrderBy(Rule):
    id: str = "unbounded-order-by"
    code: str = "SARJ096"
    description: str = "Result-level ORDER BY without LIMIT / FETCH may sort an unbounded result set."

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
            if _SELECT.search(sql) is None or not has_top_level_phrase(sql, "ORDER", "BY"):
                continue
            if has_top_level_row_cap(sql):
                continue
            if any(
                has_top_level_phrase(sql, *phrase)
                for phrase in (
                    ("FOR", "UPDATE"),
                    ("FOR", "SHARE"),
                    ("FOR", "NO", "KEY", "UPDATE"),
                    ("FOR", "KEY", "SHARE"),
                )
            ):
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        "Result-level ORDER BY has no database row cap — add LIMIT/keyset pagination, "
                        "or document why the complete result is independently bounded. Suppress with "
                        "`# sarj-noqa: SARJ096`."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags
