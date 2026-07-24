"""SARJ036: raw SQL executed in a test body — use the store/service methods.

Review quote, verbatim: "avoid raw sql in tests. can we just use service
methods". A test that runs `conn.execute("INSERT INTO call ...")` re-implements
the store layer's contract in a second place: when the schema or the store's
invariants change (a new NOT NULL column, an ON CONFLICT rule), the store is
updated but the test's private SQL is not — the test now seeds states the
application can never produce, and passes for the wrong reason. Going through
the store/service method keeps the test coupled to the real write path.

Fires when ALL of these hold:

* the file is a test file (`test_*.py`, `*_test.py`, or under a `tests`/`test`
  directory) — but NOT `conftest.py` and NOT under a `migrations` path.
  Conftest DB scaffolding (truncate-between-tests cleanup) and migration
  helpers legitimately speak raw SQL,
* the call is `<recv>.execute(...)`, `<recv>.executemany(...)`, or
  `<recv>.fetch*(...)` (any receiver: cursor, connection, pool, session),
* its first argument is a string literal (plain, `+`-concatenated, or an
  f-string's literal fragments) containing a `SELECT` / `INSERT` / `UPDATE` /
  `DELETE` keyword — matched on `_sql.strip_sql_noise`-masked text, so a
  keyword inside a quoted SQL *value* or a SQL comment never counts, and
  matched on word boundaries, so `fetch_by_name("select_option")` never counts.

SQL built in a variable and passed by name is not chased — deterministic,
call-site-visible literals only.

A test that deliberately probes the schema itself (e.g. asserting a trigger or
constraint fires) is suppressed with `# sarj-noqa: SARJ036 — <reason>`.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._sql import sql_string_value, strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path


_EXECUTE_METHODS = frozenset({"execute", "executemany"})
_FETCH_PREFIX = "fetch"

_SQL_KEYWORD_RE = re.compile(r"\b(?:select|insert|update|delete)\b", re.IGNORECASE)


class NoRawSqlInTests(Rule):
    """Raw SQL string executed in a test — go through the store/service method."""

    id: str = "no-raw-sql-in-tests"
    code: str = "SARJ036"
    description: str = (
        "raw SQL literal executed in a test re-implements the store contract — "
        "seed and read through the store/service methods instead."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or path.name == "conftest.py" or "migrations" in path.parts:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            method = _sql_method_name(node.func)
            if method is None or not node.args:
                continue
            literal = _literal_text(node.args[0])
            if literal is None or not _SQL_KEYWORD_RE.search(strip_sql_noise(literal)):
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"raw SQL literal in `.{method}(...)` inside a test — "
                        "use the store/service method so the test exercises the "
                        "real write/read path."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _sql_method_name(func: ast.expr) -> str | None:
    """Return the method name when `func` is a SQL-executing attribute call.

    Returns:
        The method name (`execute`, `fetchrow`, ...), or None.

    """
    if not isinstance(func, ast.Attribute):
        return None
    attr = func.attr
    if attr in _EXECUTE_METHODS or attr.startswith(_FETCH_PREFIX):
        return attr
    return None


def _literal_text(node: ast.expr) -> str | None:
    """Extract the literal text of a string argument, f-strings included.

    For an f-string only the constant fragments are kept; each interpolation
    becomes a single space so keywords never form across an interpolation
    boundary.

    Returns:
        The literal text, or None when the argument is not a string literal.

    """
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
