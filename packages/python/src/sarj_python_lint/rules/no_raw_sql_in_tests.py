"""SARJ036: raw SQL INSERT executed in a test body — seed through the store.

Review quote, verbatim: "avoid raw sql in tests. can we just use service
methods". A test that runs `conn.execute("INSERT INTO call ...")` re-implements
the store layer's write contract in a second place: when the schema or the
store's invariants change (a new NOT NULL column, an ON CONFLICT rule), the
store is updated but the test's private SQL is not — the test now seeds states
the application can never produce, and passes for the wrong reason. Going
through the store/service method keeps the test coupled to the real write path.

Fires when ALL of these hold:

* the file is a test file (`test_*.py`, `*_test.py`, or under a `tests`/`test`
  directory) — but NOT `conftest.py` and NOT under a `migrations` path.
  Conftest DB scaffolding (truncate-between-tests cleanup) and migration
  helpers legitimately speak raw SQL,
* the call is `<recv>.execute(...)`, `<recv>.executemany(...)`, or
  `<recv>.executescript(...)` (any receiver: cursor, connection, pool,
  session),
* its first argument is a string literal (plain, `+`-concatenated, or an
  f-string's literal fragments) — optionally wrapped in a single-argument
  `text(...)` / `sa.text(...)` / `sqlalchemy.text(...)` call, since SQLAlchemy
  2.0 mandates `text()` for raw SQL — containing a structural `INSERT INTO`,
  matched on `_sql.strip_sql_noise`-masked text so `INSERT INTO` inside a
  quoted SQL *value* or a SQL comment never counts.

Deliberately NOT flagged — a blind population analysis of all four production
corpora showed each of these is a legitimate, pervasive test idiom, and
flagging them put the rule at ~79% false positives:

* `SELECT` — `SELECT count(*)` / `SELECT ...` in a test is an *assertion* about
  database state, often deliberately independent of the store's read path,
* `DELETE` — per-test teardown/cleanup in the test body,
* `UPDATE` — time-travel setup (`SET created_at = NOW() - interval ...`) that
  no store method exposes on purpose,
* `.fetch*()` calls — asyncpg read helpers serve the same assertion role, and
  the loose prefix also swallowed unrelated `fetch_completion`/`fetch_json`
  helpers.

Only a structural INSERT bypasses the store's write invariants in a way the
mined review feedback ("use service methods to seed") actually objected to.

SQL built in a variable and passed by name is not chased — deterministic,
call-site-visible literals only.

A test that deliberately probes the schema itself (e.g. asserting a trigger or
constraint fires on INSERT) is suppressed with
`# sarj-noqa: SARJ036 — <reason>`.
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


_EXECUTE_METHODS = frozenset({"execute", "executemany", "executescript"})
_TEXT_WRAPPER_NAMES = frozenset({"sa", "sqlalchemy"})

_INSERT_RE = re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE)


class NoRawSqlInTests(Rule):
    """Raw SQL INSERT executed in a test — seed through the store/service method."""

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
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
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
    """Unwrap a single-argument `text(...)` / `sa.text(...)` / `sqlalchemy.text(...)`.

    SQLAlchemy 2.0 requires raw SQL to be wrapped in `text()`, so the literal
    of interest sits one call deeper.

    Returns:
        The wrapped argument, or `node` itself when it is not a text() call.

    """
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
