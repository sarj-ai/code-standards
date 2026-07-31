# `no-offset-pagination` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-offset-pagination.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

TS port of SARJ025 (`no-offset-pagination`). `LIMIT n OFFSET m`
makes the database scan and discard every one of the `m` skipped rows before
returning the page, so page N costs O(N): deep pages get linearly slower until
they blow the request budget. Worse, under concurrent inserts the offset window
shifts between requests, so a row can be returned twice or skipped entirely —
a paginated backfill silently misses records. Keyset / cursor pagination
(`WHERE id > ? ORDER BY id LIMIT n`) is O(page) and stable.

The rule reads statically-resolvable SQL strings (literals, template literals,
`+` concatenations, `[...].join(" ")` fragment arrays), neutralizes string
values and `--` / comment bodies first, and flags an `OFFSET` keyword
immediately followed by a value/param token — `?` or `?1` (SQLite/D1), `:name`,
`@name`, `$1`, or a bare digit. A `${...}` substitution has already become `?`
by then, so an interpolated offset is caught too.

Requiring the value token is what keeps false positives at zero: it excludes
the English word ("offset out of range", "no base offset"), an `'offset'`
string value or object key, and array-index constructs like BigQuery's
`UNNEST(...) WITH OFFSET AS col`, none of which put a value after the keyword.

    // flagged
    `SELECT id, status FROM runs ORDER BY created_at LIMIT ? OFFSET ?`

    // preferred
    `SELECT id, status FROM runs WHERE id > ? ORDER BY id LIMIT ?`

Test files are out of scope — a bounded fixture query is not a production
pagination path.

CONVERGED WITH SARJ025 AND SARJ107 (2026-07). The concept is implemented three
times — here, in `packages/python/src/sarj_python_lint/rules/
no_offset_pagination.py` (SARJ025) and in
`packages/sql/src/sarj_sql_lint/rules/no_limit_offset.py` (SARJ107). This rule
and SARJ025 both required the value token and both documented why; SARJ107 was
a bare `\bOFFSET\b` and fired on `ALTER TABLE t ADD COLUMN offset INTEGER`,
and SARJ025's parameter set omitted `?`, so the `LIMIT ? OFFSET ?` spelling
this file uses as its own headline example was a silent false negative in
Python. Both are fixed, and all three now share ONE parameter alternation —
the union of the markers each dialect uses (`%s`, `%(name)s`, `?`, `?1`,
`:name`, `@name`, `$1`, digit) — so a marker added for one language cannot go
missing in another. `%s` is inert in TypeScript today; it is present so the
three patterns are literally identical and a diff between them is a bug.
Corpus delta here: 0 findings before and after over 748 first-party TS/TSX
files (the `typescript/` and `sdks/typescript` trees of one repo, plus one
front-end repo).

## Evidence relocated from the source

### `export default createRule<Options, MessageIds>({`

`OFFSET` followed by a value/param token — the real pagination construct.
The parameter alternatives are the UNION of every marker the three packages
see, and are kept identical in SARJ025 and SARJ107 — see the header.

