# SARJ018 `store-insert-requires-on-conflict` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_store_insert_requires_on_conflict.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

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
