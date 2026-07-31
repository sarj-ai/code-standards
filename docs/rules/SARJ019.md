# SARJ019 `no-query-with-many-joins` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_query_with_many_joins.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Three years of store reviews repeatedly push back on multi-table joins inside a
single store query ("can we remove the joins?", "do the join at the application
layer", "whenever I see a join my ears perk up"). A query fanning across many
tables couples models that should stay separate, is hard to index well, and
usually wants either denormalization or splitting into per-store reads joined in
application code.

This rule walks SQL string literals embedded in `.py` (the raw queries in
`*_store.py`) and flags any single query string containing **3 or more** `JOIN`
keywords. `LEFT/RIGHT/INNER/FULL/CROSS JOIN` each count as one. SQL string-literal
values and `--` / `/* */` comments are neutralized first, so a `'join'` value or
a `--` inside a quoted value never affects the count. Only strings that actually
look like a query (they contain a `FROM`) are considered, keeping false positives
low.

If a join-heavy read is genuinely the right call, suppress with
`# sarj-noqa: SARJ019 — <reason>`.
