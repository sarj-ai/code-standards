# `store-insert-requires-on-conflict` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/store-insert-requires-on-conflict.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

TS port of SARJ018 (`store-insert-requires-on-conflict`).
An embedded `INSERT INTO ... VALUES/SELECT` with no conflict clause must
become an idempotent upsert.

Store write paths run under retries, races, and replays — and on Cloudflare
Workers that is the *normal* case, not the exception: a cron trigger can fire
twice, a Queue message is redelivered on any handler throw, and a `waitUntil`
task can be retried after the response is already sent. A bare `INSERT` under
redelivery either duplicates rows (a second Slack post, a second email, a
double-counted referral) or throws on a unique-constraint violation, which
fails the handler, which triggers another redelivery. Every store write should
be `INSERT ... ON CONFLICT ... DO UPDATE` / `DO NOTHING` so replay is a no-op.

The rule reads every statically-resolvable SQL string in the file — plain
literals, template literals (`${...}` becomes a `?` parameter marker), `+`
concatenations, and `[...].join(" ")` fragment arrays — and flags one that
contains a genuine `INSERT INTO ... VALUES` / `... SELECT` write with no
conflict handling. SQL string-literal values and `--` / comment bodies are
neutralized first, so an `ON CONFLICT` living inside a quoted value never
excuses a bare insert, a `--` inside a value never eats a real clause, and
commented-out keywords neither trigger nor excuse a finding.

Deliberately NOT flagged:
- SQLite/D1's own idempotent insert forms: `INSERT OR IGNORE INTO ...` and
  `INSERT OR REPLACE INTO ...` already survive replay.
- MySQL's `ON DUPLICATE KEY UPDATE`, the same contract under another name.
- Pure reads, DDL, and `RETURNING`-only tails.
- Test files. A fresh in-memory D1 has nothing to conflict with, so fixture
  seeding legitimately uses a bare `INSERT`; flagging it would train people to
  ignore the rule.

For a deliberate append-only write (an event/audit log where duplicates are
the point) disable with an inline `eslint-disable-next-line` and a reason.

## Evidence relocated from the source

### `docs`

Cheap substring gate. Noise-stripping only ever blanks characters to spaces,
so it can never introduce a keyword the raw text lacks — a file with no
`insert` at all can never produce a finding, and most files in a repo sweep
are not SQL-bearing.

