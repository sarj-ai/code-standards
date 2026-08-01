# SARJ044 `fixture-returns-bare-tuple` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_fixture_returns_bare_tuple.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

`return org, user` makes every consumer write `org, user = setup_orgs()` and
know the order by heart. Adding a third value silently shifts every call site's
meaning rather than breaking it loudly, and a mis-ordered unpack
(`user, org = ...`) type-checks fine and fails somewhere far away. A `NamedTuple`
or a small frozen dataclass names the fields, so consumers destructure by name,
new fields are additive, and the type checker catches a swap at the call site.

This is the house rule the codebase already applies to production code, applied
to fixtures. `CLAUDE.md` states it directly for ordinary functions — "No bare
multi-field tuples across a boundary... a `NamedTuple`... never a positional
`tuple[A, B]`" — and SARJ026 enforces it there. Fixtures were never covered,
which is exactly why they drifted.

Fires when ALL of these hold:

* the file is a test file, and the function carries a `@pytest.fixture` or
  `@pytest_asyncio.fixture` decorator (in any spelling: bare, called, or
  attribute-qualified),
* and the fixture's own body has a top-level `return`/`yield` of a **tuple
  display** with at least two elements.

The nearest-enclosing-function check (the SARJ031 technique) is what makes this
safe: a factory fixture that returns a closure which itself returns a tuple is
attributed to the closure, not the fixture, and does not fire. That pattern is
common and legitimate — the tuple crosses the closure's boundary, not the
fixture's.

Deliberately NOT flagged:

* a `NamedTuple`, dataclass, or any other constructor call — those are
  `ast.Call` nodes, never `ast.Tuple`, so the correct alternative can never be
  mistaken for the smell,
* a single-element tuple — nothing to mis-order,
* a starred tuple (`return *pair, extra`) — the arity is not statically known,
* a tuple returned from a nested helper or closure inside the fixture,
* **a fixture annotated `-> tuple[A, B, ...]` whose element types are all
  syntactically distinct.** The rule's whole argument is that a reorder fails
  silently — and with distinct static types it does not: swapping the elements
  is a type error the checker reports at the call site, which is the same
  protection a `NamedTuple` would buy. Found in a first-party review regression
  on a shared store-fixtures module, on a fixture returning
  `-> tuple[PsqlOrderStore, PsqlWidgetStore]`. A repeated type
  (`tuple[str, str]`) still fires: there the reorder really is silent.

## Implementation notes

### `_returns_distinctly_typed_tuple`

A reorder of `tuple[Store, User]` is a type error the checker catches; a
reorder of `tuple[str, str]` is silent. Only the latter is what this rule
exists to prevent, so the former is exempt.
