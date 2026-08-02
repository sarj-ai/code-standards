"""SARJ013 — Psycopg `row_factory=dict_row` where a validated model row is intended.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_class_row.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes


if TYPE_CHECKING:
    from pathlib import Path


_ROW_FACTORY_KW = "row_factory"
_BANNED_FACTORY = "dict_row"


class PreferClassRow(Rule):
    id: str = "prefer-class-row"
    code: str = "SARJ013"
    description: str = "psycopg row_factory=dict_row returns unvalidated dicts — prefer class_row(Model)."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.keyword):
            if node.arg != _ROW_FACTORY_KW:
                continue
            if _factory_name(node.value) != _BANNED_FACTORY:
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.value.lineno,
                    col=node.value.col_offset + 1,
                    code=self.code,
                    message=(
                        "`row_factory=dict_row` yields unvalidated dict rows — "
                        "prefer `class_row(YourModel)` to validate at the DB boundary "
                        "(suppress with `# sarj-noqa: SARJ013` for genuine ad-hoc shapes)"
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _factory_name(node: ast.expr) -> str | None:
    """Resolve a `row_factory=` value to its callable name (`dict_row`, …)."""
    if isinstance(node, ast.NamedExpr):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None
