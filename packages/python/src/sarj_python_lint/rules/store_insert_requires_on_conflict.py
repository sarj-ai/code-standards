"""SARJ018 — Embedded `INSERT INTO ... VALUES/SELECT` in store code must be an upsert.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_store_insert_requires_on_conflict.py
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


# Strict keyword adjacency distinguishes SQL writes from prose.
_INSERT_WRITE = re.compile(
    r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+[\w.\"'`?$:@-]+\s*(?:\([^)]*\)\s*)?(?:VALUES|SELECT|DEFAULT\s+VALUES)\b",
    re.IGNORECASE,
)

# Replay-safe conflict handling supported across the repository's SQL dialects.
_CONFLICT_HANDLED = re.compile(
    r"\bON\s+CONFLICT\b|\bON\s+DUPLICATE\s+KEY\b|\bINSERT\s+OR\s+(?:IGNORE|REPLACE)\b",
    re.IGNORECASE,
)


class StoreInsertRequiresOnConflict(Rule):
    id: str = "store-insert-requires-on-conflict"
    code: str = "SARJ018"
    description: str = (
        "Embedded SQL INSERTs in store code must use ON CONFLICT, ON DUPLICATE KEY, or SQLite OR IGNORE/REPLACE."
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

            # A Postgres ``DO $tag$ ... $tag$`` body is executable code, not a
            # scalar SQL value, so embedded writes remain visible to SARJ018.
            sql = strip_sql_noise(text, mask_dollar_quotes=False)
            if _INSERT_WRITE.search(sql) is None or _CONFLICT_HANDLED.search(sql):
                continue

            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        "Store write must be an idempotent upsert — add "
                        "`ON CONFLICT ... DO UPDATE` (or `DO NOTHING`). "
                        "Suppress with `# sarj-noqa: SARJ018` for a deliberate "
                        "non-upsert write (e.g. ClickHouse)."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags
