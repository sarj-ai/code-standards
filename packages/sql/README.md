# sarj-sql-lint

Deterministic PostgreSQL migration rules. They enforce safe timestamps,
idempotent DDL and seed data, portable types, cursor pagination, non-blocking
indexes, and ordered UUID defaults.

```bash
uv tool install sarj-sql-lint
sarj-sql-lint list-rules
sarj-sql-lint check --rule enforce-timestamptz migrations/
```

Sarj repositories normally run the package through `sarj-standards check`.
Diagnostics use `path:line:column: CODE message`. Suppress an intentional
finding on the relevant line with an exact code, for example
`-- sarj-noqa: SARJ101 -- reason`.

The scanner masks comments, strings, quoted identifiers, and dollar-quoted
bodies before matching syntax. Each registry entry under
`src/sarj_sql_lint/rules/` and its paired test are the authoritative rule
specification. Run `sarj-standards show rules` for the current catalog.
