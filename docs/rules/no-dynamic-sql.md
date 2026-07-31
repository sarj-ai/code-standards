# `no-dynamic-sql` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-dynamic-sql.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Disallow building a SQL statement out of runtime values.

`db.prepare(sql)` takes a STATIC statement plus `?` / `$1` placeholders bound
through `.bind(...)`. Interpolating a value into the statement text bypasses
the binding layer completely: that is SQL injection, and it also defeats the
driver's prepared-statement cache, because every distinct value produces a
distinct statement to compile. The shape is identical across Cloudflare D1,
better-sqlite3 and node-postgres, so the rule is driver-agnostic.

WHAT IT CATCHES
  db.prepare(`select * from users where id = '${userId}'`)
  db.prepare("select * from users where id = '" + userId + "'")
  db.exec(`delete from sessions where token = '${token}'`)

NOT FLAGGED
  - `${CONSTANT_CASE}` fragments. A module-level constant — the column-list
    constants several repos keep (`${CANDIDATE_COLS}`, `${TABLES.USERS}`) —
    is a compile-time value, not user input. Anything starting lowercase is
    treated as runtime data.
  - A template literal with no interpolations at all.
  - Tagged templates (`` sql`select ... ${id}` ``). A tag function receives the
    static strings and the values separately and is the parameterising
    mechanism, not a bypass of it.
  - `.prepare()` on something that is not a database. Requiring an
    interpolated runtime value keeps this rare in practice.
  - A statement text that contains no SQL data-statement keyword. `exec` and
    `query` are not SQL-specific names: a 5-repo sweep of real TypeScript
    (zod / TanStack Query / react-router / swr / zustand, 2,186 files) found
    4/4 hits were `child_process.exec` building a SHELL command line —
    an `open <url>` at
    react-router/integration/helpers/playwright-fixture.ts:230 and an
    `npm view <pkg>@<version> version` at
    react-router/scripts/changes/publish.ts:111. Requiring the statement to
    actually read as SQL (`SELECT` / `INSERT INTO` / `UPDATE` / `DELETE FROM`
    / DDL / `PRAGMA` / a CTE head) takes that class to zero without touching
    any real injection: an interpolated statement with no SQL verb in it was
    never a SQL statement.

CONFIGURATION
`methods` is the list of statement-taking method names to inspect. Extend it
for a driver that names things differently:

  "@sarj/no-dynamic-sql": ["error", { "methods": ["prepare", "exec", "raw"] }]

Supplying `methods` REPLACES the defaults.
