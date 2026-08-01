# `_sql` — evidence

Shared helper. This file holds what the code cannot: the measurements behind
each threshold, the false-positive families the guards exist to stop, and the
alternatives that were rejected.

Shared SQL-literal helpers for the SQL-aware store-lint rules.
TS port of Python's `rules/_sql.py`, adapted to where SQL actually lives in a
TypeScript / Cloudflare Workers codebase: D1 `db.prepare(`...`)` template
literals, `sql` tagged templates, `+`-concatenated fragments, and
`[...].join(" ")` arrays of one-line fragments.

These rules scan raw SQL for keywords (`INSERT`, `ON CONFLICT`, `OFFSET`,
`*`, ...). Scanning the raw text conflates SQL *code* with SQL string-literal
*values*: `WHERE p = 'on conflict'` holds no upsert clause, a `--` inside a
quoted value is not a comment, and `'*'` inside a value is not a projection
star. `stripSqlNoise` neutralizes both classes of noise before any keyword
scan — that single step is what keeps the false-positive rate of these rules
near zero.

Template-literal substitutions (`${cols}`, `${values}`) are replaced with the
SQLite/D1 parameter marker `?` rather than dropped, so `LIMIT ? OFFSET ${n}`
still reads as a parameterised pagination clause and an interpolated
`VALUES ${rows}` still reads as an insert write.
