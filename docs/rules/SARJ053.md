# SARJ053 `no-gen-random-uuid-in-sql` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_gen_random_uuid_in_sql.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

`gen_random_uuid()` returns a UUIDv4: 122 random bits with no time component.
As a primary-key default that is the worst possible insert pattern for a B-tree
— every row lands in a random leaf page, so the index's write set is the whole
index rather than its right edge, and a table that no longer fits in shared
buffers pays a random read per insert. UUIDv7 puts a millisecond timestamp in
the high bits, so inserts append, recent rows cluster on the same pages, and
range scans over "recent" become sequential. Postgres 18 ships `uuidv7()` in
core.

This is the embedded-SQL half of a policy the stack already states in two other
places: `ruff.strict.toml` bans `uuid.uuid4` ("use `uuid.uuid7()` — time-ordered,
aligns with the DB `uuidv7()` default"), and `sarj-sql-lint`'s SARJ109
`prefer-uuidv7-default` enforces it in `.sql` migration files. Neither can see
SQL that lives inside a Python string, which is where `CREATE TABLE` statements
in test fixtures, ad-hoc DDL and store-layer `INSERT`s actually sit.

Fires when a Python string literal both:

* contains `gen_random_uuid(` outside a SQL comment or a quoted SQL value
  (checked against `_sql.strip_sql_noise`-masked text, so a `--` remark or a
  literal `'gen_random_uuid()'` value never counts), and
* looks like SQL at all — it must also contain one of the structural keywords
  `CREATE` / `ALTER` / `INSERT` / `UPDATE` / `SELECT` / `DEFAULT` / `VALUES`.

That second condition is what keeps prose out: a docstring, a comment string or
an error message that merely *names* the function is not a SQL statement, and
this rule is about the DDL, not the word.

**Not flagged: SQL that is itself building a UUIDv7.** On Postgres < 18 the
portable way to get `uuidv7()` is to define it, and every such definition draws
its 74 random bits from `gen_random_uuid()` or `gen_random_bytes()` and then
overwrites the high bits with a timestamp. Airflow's
`0042_3_0_0_add_uuid_primary_key_to_task_instance_.py` is exactly that — a
`CREATE OR REPLACE FUNCTION uuid_generate_v7(...)` whose pgcrypto-less fallback
is `substring(uuid_send(gen_random_uuid()) FROM 1 FOR 5) || ...`. Telling that
code to "use uuidv7() instead" is telling the definition of uuidv7 to call
itself, so a string that names `uuid_generate_v7` / `uuidv7` / `uuid7`, or feeds
`gen_random_uuid()` into `uuid_send`/`substring`/`set_byte`/`encode` rather than
into a column, is left alone. Measured: this was 1 of the 2 hits the rule
produced over 26,000 external files.

Generated files are exempt — they mirror whatever their generator emits.

A deliberate use (reproducing a legacy default in a data-migration test,
asserting on an existing column's `pg_get_expr`) is suppressed with
`# sarj-noqa: SARJ053 — <reason>`.
