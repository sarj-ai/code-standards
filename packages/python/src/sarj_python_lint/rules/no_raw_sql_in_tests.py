"""SARJ036 — Raw SQL INSERT executed in a test body — seed through the store.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_raw_sql_in_tests.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._sql import sql_string_value, strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path


_EXECUTE_METHODS = frozenset({"execute", "executemany", "executescript"})
_TEXT_WRAPPER_NAMES = frozenset({"sa", "sqlalchemy"})

_INSERT_RE = re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE)


class NoRawSqlInTests(Rule):
    id: str = "no-raw-sql-in-tests"
    code: str = "SARJ036"
    description: str = (
        "raw SQL INSERT executed in a test bypasses the store's write "
        "invariants — seed through the store/service methods instead."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or path.name == "conftest.py" or "migrations" in path.parts:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.Call):
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr in _EXECUTE_METHODS) or not node.args:
                continue
            method = func.attr
            literal = _literal_text(_unwrap_text_call(node.args[0]))
            if literal is None or not _INSERT_RE.search(strip_sql_noise(literal)):
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"raw SQL INSERT in `.{method}(...)` inside a test — "
                        "seed through the store/service method so the test "
                        "exercises the real write path."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _unwrap_text_call(node: ast.expr) -> ast.expr:
    """Unwrap a single-argument `text(...)` / `sa.text(...)` / `sqlalchemy.text(...)`."""
    match node:
        case ast.Call(func=func, args=[inner], keywords=[]):
            match func:
                case ast.Name(id="text"):
                    return inner
                case ast.Attribute(attr="text", value=ast.Name(id=recv)) if recv in _TEXT_WRAPPER_NAMES:
                    return inner
                case _:
                    return node
        case _:
            return node


def _literal_text(node: ast.expr) -> str | None:
    """Extract the literal text of a string argument, f-strings included."""
    direct = sql_string_value(node)
    if direct is not None:
        return direct
    if not isinstance(node, ast.JoinedStr):
        return None
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            parts.append(" ")
    return "".join(parts)
