# SARJ036 `no-raw-sql-in-tests` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_raw_sql_in_tests.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

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

## Implementation notes

### `_literal_text`

For an f-string only the constant fragments are kept; each interpolation
becomes a single space so keywords never form across an interpolation
boundary.

### `_unwrap_text_call`

SQLAlchemy 2.0 requires raw SQL to be wrapped in `text()`, so the literal
of interest sits one call deeper.
