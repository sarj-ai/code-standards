# SARJ025 `no-offset-pagination` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_offset_pagination.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

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
