"""SARJ097 — Avoid sorting an entire candidate set by a random function.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_order_by_random.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, Severity, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._sql import is_store_module, sql_string_value, strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path


_RANDOM_ORDER = re.compile(
    r"\bORDER\s+BY\b(?:(?!\b(?:LIMIT|FETCH|OFFSET|FOR)\b)[\s\S])*?\b(?:RANDOM|RAND)\s*\(",
    re.IGNORECASE,
)
_SELECT = re.compile(r"\bSELECT\b[\s\S]*?\bFROM\b", re.IGNORECASE)


class NoOrderByRandom(Rule):
    id: str = "no-order-by-random"
    code: str = "SARJ097"
    description: str = "ORDER BY RANDOM()/RAND() evaluates and sorts the full candidate set."

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
            if _SELECT.search(sql) is None or _RANDOM_ORDER.search(sql) is None:
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        "ORDER BY RANDOM()/RAND() evaluates and sorts the full candidate set — use a "
                        "precomputed sampling key or a bounded sampling strategy. Suppress with "
                        "`# sarj-noqa: SARJ097`."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags
