# `no-select-star` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-select-star.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

TS port of SARJ021 (`no-select-star`). `SELECT *` over-fetches
every column (including large JSON/text blobs the caller never reads) and,
more importantly, makes the row shape implicit: the moment a column is added,
renamed, or reordered, the zod schema that parses the row starts failing — or
worse, silently accepts extra keys — and nothing in the query says which
columns the code actually depends on. Naming the columns makes the dependency
explicit and pins the row contract at the query.

The rule reads statically-resolvable SQL strings (literals, template literals,
`+` concatenations, `[...].join(" ")` fragment arrays), neutralizes string
values and `--` / comment bodies first (so a `'*'` value is never mistaken for
a star), and flags a query — a string with a real `SELECT ... FROM` shape —
whose projection list holds a `*` in any position: bare (`SELECT *`,
`SELECT id, *`) or qualified (`c.*`, `main.runs.*`).

Deliberately NOT flagged, matching the Python rule's tuning:
- `COUNT(*)` and other aggregate stars — the star is a function argument, not
  a projection.
- `a * b` arithmetic — an operand follows the star.
- `EXISTS (SELECT * ...)` — the projection is unused by definition.
- Prose that merely contains the words "select" and "from".
- Test files, where a `SELECT *` assertion over a fixture table is fine.

## Evidence relocated from the source

### `/**`

 Cheap substring gate; a file with no star and no SELECT can never produce a finding.

