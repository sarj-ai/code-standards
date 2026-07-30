"""SARJ013: psycopg `row_factory=dict_row` where a validated model row is intended.

The repo standard is to map each DB row straight into a pydantic model with
`class_row(Model)`, so every row is validated at the database boundary and the
cursor is typed `Cursor[Model]`. `dict_row` instead hands back an unvalidated
`dict[str, Any]` that callers then feed to `Model.model_validate(...)` by hand —
an extra step that is easy to forget and leaves the value untyped in between.

Flags any `row_factory=dict_row` keyword argument (typically on
`conn.cursor(...)`). If you genuinely need a plain mapping — an ad-hoc
aggregate, a `COUNT(*)`, or a dynamic projection with no model — suppress with
`# sarj-noqa: SARJ013 — <reason>`.

Replace:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(..., RETURNING id, status)
        row = await cur.fetchone()
        return Task.model_validate(row)

with:
    async with conn.cursor(row_factory=class_row(Task)) as cur:
        await cur.execute(..., RETURNING id, status)
        return one(await cur.fetchone())

References:
- https://www.psycopg.org/psycopg3/docs/api/rows.html#psycopg.rows.class_row
- https://docs.pydantic.dev/latest/concepts/models/#validating-data

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
    """`row_factory=dict_row` returns unvalidated dicts — prefer `class_row(Model)`."""

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
    """Resolve a `row_factory=` value to its callable name (`dict_row`, …).

    Returns:
        The callable name, or None when it cannot be resolved.

    """
    if isinstance(node, ast.NamedExpr):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None
