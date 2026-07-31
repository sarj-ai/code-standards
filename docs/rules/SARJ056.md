# SARJ056 `no-optional-tenant-predicate` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_optional_tenant_predicate.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Multi-tenant stores compose a WHERE clause by accumulating fragments in a list::

    where_conditions: list[Composable] = []
    if args.organization_ids:
        where_conditions.append(SQL("organization_id = ANY(%s::uuid[])"))
    if args.status:
        where_conditions.append(SQL("status = ANY(%s)"))
    where_clause = SQL(" AND ").join(where_conditions) if where_conditions else SQL("1=1")

When the tenant fragment is the *only* thing standing between a caller and every
other tenant's rows, guarding it with `if` makes the scoping **fail open**: the
query still executes, just without the predicate. A caller that passes an empty
or missing organization list silently reads the whole table.

This is not hypothetical. In one first-party service,
`PsqlOrderStore._build_filter_conditions` had exactly this shape, and
`POST /v1/orders/list` reached it with `organization_ids=[]` for any user whose
`organization_id` was NULL — composing `SELECT ... FROM orders WHERE 1=1`, i.e.
every tenant's rows.

The rule fires when, within a single function, *every* WHERE-fragment that
mentions a tenant column is nested inside a conditional. The safe idiom seeds
the fragment list with the tenant predicate unconditionally::

    conditions: list[Composable] = [SQL("organization_id = %s")]   # always applied

so that form never fires. A function with no tenant fragment at all does not
fire either — an intentionally cross-tenant admin query is not this rule's
business; only *attempted-but-optional* scoping is.

Scope note: only fragments participating in list composition (a list literal, or
an argument to `.append()` / `.extend()`) are considered, so an unrelated inline
`WHERE organization_id = %s` elsewhere in the same function neither triggers nor
masks a finding.

## Implementation notes

### `_mentions_tenant_predicate`

Walking the subtree catches `SQL("organization_id = %s")` and the
`SQL("...").format(...)` form alike.

### `_composition_fragments`

Shallow by design — the caller recurses — so each node is inspected once.

### `_tenant_fragments`

Only fragments taking part in list composition count: elements of a list
literal, or arguments to `.append()` / `.extend()`. Each is paired with
whether it sits inside a conditional *within this function*.

One recursive pass carries the "am I under an `If`/`IfExp`?" flag down the
tree, so the cost is linear in the function's node count.
