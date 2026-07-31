# SARJ013 `prefer-class-row` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_class_row.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

The repo standard is to map each DB row straight into a pydantic model with
`class_row(Model)`, so every row is validated at the database boundary and the
cursor is typed `Cursor[Model]`. `dict_row` instead hands back an unvalidated
`dict[str, Any]` that callers then feed to `Model.model_validate(...)` by hand —
an extra step that is easy to forget and leaves the value untyped in between.

Flags any `row_factory=dict_row` keyword argument (typically on
`conn.cursor(...)`). If you genuinely need a plain mapping — an ad-hoc
aggregate, a `COUNT(*)`, or a dynamic projection with no model — suppress with
`# sarj-noqa: SARJ013 — <reason>`.

Replace:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(..., RETURNING id, status)
        row = await cur.fetchone()
        return Task.model_validate(row)

with:
    async with conn.cursor(row_factory=class_row(Task)) as cur:
        await cur.execute(..., RETURNING id, status)
        return one(await cur.fetchone())

References:
- https://www.psycopg.org/psycopg3/docs/api/rows.html#psycopg.rows.class_row
- https://docs.pydantic.dev/latest/concepts/models/#validating-data
