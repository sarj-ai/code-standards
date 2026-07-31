"""Shared SQL-literal helpers for the SQL-aware store-lint rules (SARJ018-021).

These rules scan raw SQL embedded in Python string literals for keywords
(`JOIN`, `COUNT`, `ON CONFLICT`, `*`, ...). Scanning the raw text conflates SQL
*code* with SQL string-literal *values*: `WHERE p = 'join'` holds no JOIN, a
`--` inside a quoted value is not a comment, and a backtick inside a value is not
a BigQuery table quote. `strip_sql_noise` neutralizes both classes of noise
before any keyword or comment scan.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


def is_store_module(path: Path) -> bool:
    """Report whether `path` is a store-layer module: basename ends `_store.py`, or lives under a `stores/` directory.

    The SQL store-lint rules (SARJ018/020/021) encode store-write semantics —
    column-naming, ON-CONFLICT upserts, no Postgres-side aggregation — that only
    apply to the store layer. Non-store SQL (Flask view handlers, a Django ORM
    SQL generator) legitimately writes `SELECT *`, bare `INSERT`, and `COUNT()`,
    so those files are out of scope.

    TEST FILES ARE NEVER STORE MODULES. `test_<x>_store.py` ends with `_store.py`,
    so the naming test alone swept the *tests for* the store layer into the rules
    written for the store layer itself. Every store-semantics premise fails there:
    a test asserts over a handful of per-test fixture rows (so a `COUNT(*)` is not
    a hot-path aggregation competing with OLTP traffic), and a fixture seeds a row
    exactly once (so a bare `INSERT` needs no `ON CONFLICT` — idempotency is what
    the per-test database reset provides). Raw SQL in tests already has its own
    rule, SARJ036 no-raw-sql-in-tests, which judges it on test-appropriate terms.

    Evidence from a first-party review regression (all suppressed at PR head,
    none a defect):
      - SARJ020, three sites across two store test modules — two counting rows
        ("test assertion count over per-test fixture rows") and one asserting
        exactly one row exists after an upsert.
      - SARJ018, one site where a seed helper inserts a single provider row per
        test.

    Returns:
        True when `path` belongs to the store layer.

    """
    if is_test_path(path):
        return False
    return path.name.endswith("_store.py") or "stores" in path.parts


def sql_string_value(node: ast.expr) -> str | None:
    """Reconstruct a (possibly `+`-concatenated) string literal, else None.

    Returns:
        The reconstructed string, or None when `node` is not a string literal.

    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = sql_string_value(node.left)
        right = sql_string_value(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def strip_sql_noise(text: str) -> str:
    """Blank out SQL string-literal contents and comment bodies.

    A single left-to-right scan, so precedence between strings and comments is
    correct: a `--` or quote inside a string literal is protected (masked as
    string data, never read as a comment), and a quote inside a comment is
    ignored. Every masked character becomes a space except newlines, which are
    preserved so line offsets — and therefore diagnostic positions — do not
    shift. Doubled quotes (`''` / `""`) are SQL's in-string escape and keep the
    scanner inside the literal.

    Returns:
        `text` with string-literal contents and comment bodies blanked out.

    """
    out = list(text)
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch in {"'", '"'}:
            out[i] = " "
            i += 1
            while i < n:
                c = text[i]
                if c == ch:
                    if i + 1 < n and text[i + 1] == ch:
                        out[i] = out[i + 1] = " "
                        i += 2
                        continue
                    out[i] = " "
                    i += 1
                    break
                if c != "\n":
                    out[i] = " "
                i += 1
            continue
        if ch == "-" and i + 1 < n and text[i + 1] == "-":
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            out[i] = out[i + 1] = " "
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
                i += 1
                if i < n:
                    out[i] = " "
                    i += 1
            continue
        i += 1
    return "".join(out)
