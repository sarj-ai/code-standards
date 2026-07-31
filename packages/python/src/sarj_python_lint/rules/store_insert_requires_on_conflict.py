"""SARJ018: embedded `INSERT INTO ... VALUES/SELECT` in store code must be an upsert.

Store write paths run under retries, races, and replays. A bare `INSERT`
either duplicates rows or crashes on a unique-constraint violation; the repo
standard is to make every store write an idempotent upsert
(`INSERT ... ON CONFLICT ... DO UPDATE` / `DO NOTHING`). This is the same rule
SARJ105 enforces for `.sql` migrations, applied to the raw SQL embedded in
`*_store.py` Python (the args to `cur.execute(...)`, `SQL("...")`, etc.).

This rule walks string literals (including `a + b` concatenations and adjacent
implicitly-concatenated literals, which Python already folds into one constant)
and flags any that contain a genuine `INSERT INTO ... VALUES` / `INSERT INTO
... SELECT` write with no `ON CONFLICT` clause. SQL string-literal values and
`--` / `/* */` comments are neutralized first, so an `ON CONFLICT` living inside
a quoted value never excuses a bare insert, a `--` inside a value never eats a
real clause, and commented-out keywords neither trigger nor excuse a finding.
Pure reads (`SELECT`), `RETURNING`-only tails, and statements that already carry
`ON CONFLICT` are left alone.

ClickHouse has no `ON CONFLICT`; for a genuine ClickHouse insert (or any other
deliberate non-upsert write) suppress with `# sarj-noqa: SARJ018 — <reason>`.

CONVERGED WITH SARJ105 AND THE TS TWIN (2026-07)
------------------------------------------------
This concept is implemented three times — here, in SARJ105
(`packages/sql/src/sarj_sql_lint/rules/insert_requires_on_conflict.py`, for
`.sql` migrations) and in
`packages/typescript/src/rules/store-insert-requires-on-conflict.ts`. All three
had drifted to a different definition of "already idempotent" and a different
detection strength. Two changes landed here:

1. **One definition of "already idempotent."** Only `ON CONFLICT` used to be
   recognised, so a MySQL `ON DUPLICATE KEY UPDATE` upsert was a false positive
   here and in SARJ105 while the TS twin correctly excused it. All three now
   accept `ON CONFLICT`, `ON DUPLICATE KEY`, and SQLite/D1's `INSERT OR IGNORE` /
   `INSERT OR REPLACE`. (The last two were already silently un-flagged here, but
   only by accident: the old pattern required a literal `INSERT INTO`, so
   `INSERT OR IGNORE INTO` was not recognised as an insert at all. It is now
   detected and then deliberately excused, which is the same outcome for the
   right reason — and means a future `INSERT OR ABORT` is still caught.)

2. **Strict adjacency instead of `.*?` under `DOTALL`.** The old pattern let any
   text — including a `;` and a whole following statement — sit between
   `INSERT INTO` and the write verb. That matched English prose: the string
   `"failed to insert into the queue: values were rejected by the broker"`
   produced a finding, because `insert into` … `values` is a match once `.*?`
   may span anything. The rule now requires the TS twin's shape — keyword, table
   identifier, optional column list, then the verb — which is exactly what keeps
   prose out. Zero corpus delta on the two first-party repos (22 findings before
   and after, all genuine bare `INSERT ... VALUES` store writes such as an
   API-key store's insert); this is
   false-positive prevention, not a count change.

DELIBERATE, DOCUMENTED DIVERGENCES from SARJ105, both structural rather than
drift — do not "fix" them:
  - **Reporting granularity.** This rule reports once per string *literal*;
    SARJ105 reports once per `;`-delimited *statement*. That is the unit each
    package has: a `.sql` file is a sequence of statements and has no literals,
    while a Python literal's internal statement structure is not always
    resolvable (it may be concatenated at runtime).
  - **No dollar-quoted-body exemption.** SARJ105 exempts an `INSERT` inside a
    `DO $$ ... $$` block that guards its own replay with `IF EXISTS (...)`,
    because PL/pgSQL seed blocks in migrations do that instead of using
    `ON CONFLICT`. That exemption is deliberately not ported here: `DO $$`
    appears in **zero** Python files across the two first-party repos and their
    SDKs, and
    this rule neither masks nor descends into a dollar-quoted body. If embedded
    PL/pgSQL ever appears in a store module, SARJ105 is the precedent to follow.
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


# A real insert *write*: the keyword, a table identifier, an optional column
# list, then `VALUES` / `SELECT` / `DEFAULT VALUES` with nothing in between.
# Kept character-for-character in step with the TS twin's `INSERT_WRITE` and
# SARJ105's `INSERT_PATTERN`. The optional `OR <action>` clause is SQLite's
# conflict resolution, matched here so `INSERT OR IGNORE INTO` is recognised as
# an insert at all, then excused by `_CONFLICT_HANDLED`.
_INSERT_WRITE = re.compile(
    r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+[\w.\"'`?$:@-]+\s*(?:\([^)]*\)\s*)?(?:VALUES|SELECT|DEFAULT\s+VALUES)\b",
    re.IGNORECASE,
)

# Conflict handling that makes the write replay-safe, in all three dialects the
# repo touches. Shared spelling with SARJ105 and the TS twin.
_CONFLICT_HANDLED = re.compile(
    r"\bON\s+CONFLICT\b|\bON\s+DUPLICATE\s+KEY\b|\bINSERT\s+OR\s+(?:IGNORE|REPLACE)\b",
    re.IGNORECASE,
)


class StoreInsertRequiresOnConflict(Rule):
    """Embedded INSERT in store code without ON CONFLICT — store writes must be upserts."""

    id: str = "store-insert-requires-on-conflict"
    code: str = "SARJ018"
    description: str = (
        "Embedded SQL INSERT in store code without ON CONFLICT — store writes must be idempotent upserts."
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
