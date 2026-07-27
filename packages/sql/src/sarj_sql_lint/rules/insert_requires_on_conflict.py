"""SARJ105: `INSERT INTO` in a migration must carry conflict handling.

Migrations re-run: on replay, a bare INSERT either duplicates rows or
crashes on a unique constraint. Data writes in migrations must be
idempotent upserts (`INSERT ... ON CONFLICT ... DO UPDATE` / `DO NOTHING`).

Statements are delimited by `;`; comments and string/dollar-quote bodies are
masked first, so a `;` inside `'a;b'` does not mis-split a statement.

CONVERGED WITH SARJ018 AND THE TS TWIN (2026-07)
------------------------------------------------
This concept is implemented three times — here, in Python's SARJ018
(`store_insert_requires_on_conflict.py`, for SQL embedded in `*_store.py`) and in
`packages/typescript/src/rules/store-insert-requires-on-conflict.ts`. All three
had drifted to a different definition of "already idempotent" and a different
detection strength, so the same upsert was a finding in some packages and clean
in others. Two changes landed here to make them agree:

1. **A write-verb gate.** `INSERT INTO` alone used to be enough, which made this
   the loosest of the three — and it is the one that runs on production
   migrations. A real insert *write* is now required: the keyword, a table
   identifier, an optional column list, then `VALUES` / `SELECT` /
   `DEFAULT VALUES`. `INSERT INTO t;` (no write verb) no longer fires. Zero
   corpus delta: all 17 findings over the 239 `.sql` files of bulbul + noura-be
   are genuine `INSERT ... VALUES` / `INSERT ... SELECT` writes, e.g.
   `bulbul/svcs/clickhouse/migrations/20260619000004_audit_log_backfill.sql:2`
   (`INSERT INTO ... (cols) SELECT ...`) and
   `bulbul/svcs/db/db/schema.sql:2758` (dbmate's `schema_migrations` seed).

2. **One definition of "already idempotent."** `ON CONFLICT` was the only form
   recognised, so a MySQL `ON DUPLICATE KEY UPDATE` upsert and SQLite/D1's
   `INSERT OR IGNORE` / `INSERT OR REPLACE` were false positives here and in
   SARJ018 while the TS twin correctly excused them. All three now accept the
   same three spellings. Zero corpus delta — the `.sql` corpus contains no MySQL
   or SQLite dialect, so this is pure false-positive prevention for the day one
   appears.

DELIBERATE, DOCUMENTED DIVERGENCE — REPORTING GRANULARITY. This rule reports once
per `;`-delimited *statement*; SARJ018 and the TS twin report once per *string
literal*. That is not drift, it is the unit each package actually has: a `.sql`
file is a sequence of statements and has no literals, while a Python/TS file has
literals whose internal statement structure is not always resolvable (one literal
may be built by concatenation at runtime). Both point at the same write; only the
granularity of "the same write twice" differs. Do not try to unify it.

DOLLAR-QUOTED SEED BLOCKS. `mask_sql` keeps `DO $$ ... $$` and
`CREATE FUNCTION ... AS $$ ... $$` bodies visible as SQL, which is what lets the
rules see the DML inside them. For this rule that surfaced two false positives,
because a seed block guards its own replay procedurally instead of with
`ON CONFLICT`:
  - `noura-be/digital-bank/banking-be/migrations/022_seed_banks.sql:34` —
    `FOREACH ... LOOP / IF EXISTS (SELECT 1 FROM banks WHERE code = b[2]) THEN
    CONTINUE; END IF;` around the `INSERT INTO banks`.
  - `noura-be/digital-bank/banking-be/migrations/028_seed_ajb_bank.sql:21` — the
    same shape with `RETURN` instead of `CONTINUE`.
An `ON CONFLICT` clause there would be dead code. A dollar-quoted body is
therefore exempt **only when it carries such a guard** (`IF EXISTS (` /
`IF NOT EXISTS (`, read from the masked text so a commented-out guard does not
count). Exempting every dollar body unconditionally — the obvious one-liner —
would silently stop flagging an *unguarded* `INSERT` inside a `DO` block, which
is the very defect this rule exists to catch and is not something the corpus
justifies. Measured: 19 → 17 over bulbul + noura-be, dropping exactly the two
lines above and nothing else, with an unguarded insert in a `DO` block still
flagged.

This exemption is SQL-only, deliberately. SARJ018 and the TS twin do not need it:
`DO $$` appears in **zero** Python and **zero** TypeScript files across bulbul,
its SDKs, noura-be and noura-fe, and neither rule masks or descends into a
dollar-quoted body in the first place. If embedded PL/pgSQL ever appears there,
this is the precedent to follow.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, dollar_quoted_lines, mask_sql, split_statements


if TYPE_CHECKING:
    from pathlib import Path


# A real insert *write*: the keyword, a table identifier, an optional column
# list, then `VALUES` / `SELECT` / `DEFAULT VALUES` with nothing in between.
# Kept character-for-character in step with the TS twin's `INSERT_WRITE` and
# SARJ018's `_INSERT_WRITE`. The optional `OR <action>` clause is SQLite's
# conflict resolution, matched here so `INSERT OR IGNORE INTO` is recognised as
# an insert at all, then excused by `CONFLICT_HANDLED`.
INSERT_PATTERN = re.compile(
    r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+[\w.\"'`?$:@-]+\s*(?:\([^)]*\)\s*)?(?:VALUES|SELECT|DEFAULT\s+VALUES)\b",
    re.IGNORECASE,
)

# Where to point the diagnostic. `INSERT_PATTERN` spans from the keyword to the
# write verb and so routinely straddles lines (`INSERT INTO t (\n cols \n)\n
# SELECT ...`), which makes it useless for locating a column. This matches just
# the keyword, on one line, and is used only after the decision is made.
INSERT_KEYWORD_PATTERN = re.compile(r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\b", re.IGNORECASE)

# Conflict handling that makes the write replay-safe, in all three dialects the
# repo touches. Shared spelling with SARJ018 and the TS twin.
ON_CONFLICT_PATTERN = re.compile(
    r"\bON\s+CONFLICT\b|\bON\s+DUPLICATE\s+KEY\b|\bINSERT\s+OR\s+(?:IGNORE|REPLACE)\b",
    re.IGNORECASE,
)

# A procedural replay guard inside a `DO $$ ... $$` seed block: the block checks
# for the row itself and skips, so `ON CONFLICT` would be dead code.
REPLAY_GUARD_PATTERN = re.compile(r"\bIF\s+(?:NOT\s+)?EXISTS\s*\(", re.IGNORECASE)


def _guarded_dollar_body_lines(masked: str, source: str) -> frozenset[int]:
    """1-based line numbers inside a dollar-quoted body that guards its own replay.

    `dollar_quoted_lines` yields a flat line set; contiguous runs of it are the
    individual bodies, which is what has to be tested for a guard (one guarded
    block must not excuse an unguarded one elsewhere in the same file).

    Returns:
        The lines of every dollar-quoted body carrying an `IF (NOT) EXISTS (` guard.

    """
    inside = dollar_quoted_lines(source)
    if not inside:
        return frozenset()
    masked_lines = masked.splitlines()
    guarded: set[int] = set()
    run: list[int] = []

    def flush() -> None:
        if not run:
            return
        body = "\n".join(masked_lines[lineno - 1] for lineno in run if lineno <= len(masked_lines))
        if REPLAY_GUARD_PATTERN.search(body):
            guarded.update(run)
        run.clear()

    for lineno in sorted(inside):
        if run and lineno != run[-1] + 1:
            flush()
        run.append(lineno)
    flush()
    return frozenset(guarded)


@final
class InsertRequiresOnConflict(Rule):
    """INSERT INTO in a migration without ON CONFLICT — must be an idempotent upsert."""

    id = "insert-requires-on-conflict"
    code = "SARJ105"
    description = "INSERT without ON CONFLICT — migration data writes must be idempotent upserts."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        masked = mask_sql(source)
        exempt = _guarded_dollar_body_lines(masked, source)
        diags: list[Diagnostic] = []
        for statement in split_statements(masked):
            text = "\n".join(line for _, line in statement)
            if INSERT_PATTERN.search(text) is None or ON_CONFLICT_PATTERN.search(text):
                continue
            # Point at the line holding `INSERT INTO`; if the keywords are
            # split across lines, fall back to the statement's first line.
            lineno, col = statement[0][0], 1
            for stmt_lineno, line in statement:
                match = INSERT_KEYWORD_PATTERN.search(line)
                if match:
                    lineno, col = stmt_lineno, match.start() + 1
                    break
            if lineno in exempt:
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=lineno,
                    col=col,
                    code=self.code,
                    message=(
                        "Data writes in migrations must be idempotent upserts — "
                        "add `ON CONFLICT ... DO UPDATE` (or `DO NOTHING`)."
                    ),
                )
            )
        return diags
