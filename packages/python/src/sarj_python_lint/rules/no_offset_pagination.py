"""SARJ025: no `OFFSET` pagination in a store query — use a keyset cursor.

`LIMIT n OFFSET m` makes the database scan and discard every one of the `m`
skipped rows before returning page contents, so page N costs O(N): deep pages get
linearly slower and, under concurrent inserts, rows shift between pages (an item
can be shown twice or skipped). Keyset / cursor pagination
(`WHERE id > :cursor ORDER BY id LIMIT n`) is O(page) and stable. This mirrors the
SQL-migration linter's `no-limit-offset` (SARJ107), but for the SQL embedded in
Python store queries — where application pagination actually lives.

The rule walks SQL string literals embedded in `.py`, neutralizes string-literal
values and `--` / `/* */` comments first (so an `'offset'` value or a prose
`"offset out of range"` message is never mistaken for the keyword), and flags an
`OFFSET` keyword immediately followed by a value/param token (`%s`, `%(name)s`,
`?`, `?1`, `:name`, `@name`, `$1`, or a digit) — the real pagination construct.
Requiring the value token excludes the English word and BigQuery's
`UNNEST(...) WITH OFFSET AS col` array indexing (which has no value after
`OFFSET`).

CONVERGED WITH SARJ107 AND THE TS TWIN (2026-07). The concept is implemented
three times — here, in `packages/sql/src/sarj_sql_lint/rules/no_limit_offset.py`
(SARJ107, for `.sql` migrations) and in
`packages/typescript/src/rules/no-offset-pagination.ts`. Two defects were fixed:

  - **This rule's parameter set omitted `?`.** Every other marker was present,
    so `LIMIT %s OFFSET %s` (psycopg) fired but `LIMIT ? OFFSET ?` — the
    sqlite3 / aiosqlite / D1 spelling, and the one the TS twin's docstring uses
    as its own headline example — was a silent false negative. Any sqlite-backed
    store paginating with `?` was simply not linted. The three packages now share
    one parameter alternation, the union of what each dialect uses, so a marker
    added for one language cannot go missing in another.
  - **SARJ107 required no value token at all** — it was a bare word-boundary
    `OFFSET` match, so it fired on `ALTER TABLE t ADD COLUMN offset INTEGER`.
    Fixed there.

Corpus delta of the `?` addition over two first-party repos plus
django/fastapi/celery: 0 new findings (the first-party Python stores are
psycopg/`%s`, so the gap was latent rather than active) and 0 lost — the 4
existing findings, all in one repo's dashboard store package, are unchanged.

    # flagged
    "SELECT id, status FROM call ORDER BY created_at LIMIT %s OFFSET %s"
    " LIMIT %s OFFSET %s"          # a paginated-query fragment

    # preferred
    "SELECT id, status FROM call WHERE id > %s ORDER BY id LIMIT %s"

Suppress a deliberate case (e.g. a bounded admin export) with
`# sarj-noqa: SARJ025 — <reason>`.
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


# `OFFSET` followed by a value/param token — the real pagination construct. This
# excludes the English word ("no base offset"), `'offset'` dict keys, and BigQuery
# `UNNEST(...) WITH OFFSET AS col` (array indexing, no value token after OFFSET).
#
# The parameter alternatives are the UNION of every marker the three packages
# see, and are kept identical in SARJ107 and the TS twin — see the module
# docstring. `\?\d*` (sqlite3 / aiosqlite / D1) was missing here specifically,
# which made `LIMIT ? OFFSET ?` a silent false negative in Python while the TS
# twin caught it.
_OFFSET_PAGINATION = re.compile(
    r"\bOFFSET\s+(?:%s|%\(\w+\)s|\?\d*|:\w+|@\w+|\$\d+|\d+)",
    re.IGNORECASE,
)


class NoOffsetPagination(Rule):
    """`OFFSET` pagination in a store query — use a keyset cursor instead."""

    id: str = "no-offset-pagination"
    code: str = "SARJ025"
    description: str = (
        "OFFSET pagination is O(N) and unstable under concurrent writes — use a "
        "keyset cursor (WHERE id > :cursor ORDER BY id LIMIT n)."
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

            sql = strip_sql_noise(text)
            if _OFFSET_PAGINATION.search(sql) is None:
                continue

            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        "Store query uses OFFSET pagination (O(N), unstable under "
                        "concurrent writes) — use a keyset cursor (WHERE id > :cursor "
                        "ORDER BY id LIMIT n). Suppress with `# sarj-noqa: SARJ025`."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags
