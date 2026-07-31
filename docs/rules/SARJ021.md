# SARJ021 `no-select-star` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_select_star.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

`SELECT *` over-fetches: it pulls every column (including large JSONB / text
blobs the caller never reads), breaks `class_row(Model)` mapping the moment a
column is added or reordered, and hides which columns a query actually depends
on. The recurring review ask is to name the columns explicitly.

This rule walks SQL string literals embedded in `.py` (`*_store.py`) and flags
any query (a string containing `FROM`) whose projection list holds a `*` in any
position — bare (`SELECT *`, `SELECT id, *`), qualified (`c.*`, `public.call.*`),
or after `DISTINCT ON (...)`. SQL string-literal values and `--` / `/* */`
comments are neutralized first, so a `'*'` value is never mistaken for a star.
`COUNT(*)` is NOT flagged (the star is a function argument, not a projection),
`a * b` arithmetic is NOT flagged, and `EXISTS (SELECT * ...)` is exempt (the
columns are unused).

    # flagged
    "SELECT * FROM call WHERE id = %s"
    "SELECT c.* FROM call c"

    # preferred
    "SELECT id, status, created_at FROM call WHERE id = %s"

Suppress a deliberate case with `# sarj-noqa: SARJ021 — <reason>`.

## Implementation notes

### `_is_projection_star`

A projection star expands columns: bare (`SELECT *`, `id, *`), qualified
(`c.*`, `public.call.*`), or after `DISTINCT ON (...)`. It is NOT a
`COUNT(*)` argument (`(*)`) nor an `a * b` multiply (an operand follows).
