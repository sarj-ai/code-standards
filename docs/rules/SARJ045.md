# SARJ045 `kwarg-heavy-construction-in-test` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_kwarg_heavy_construction_in_test.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

A test that constructs `Beneficiary(id=..., name=..., iban=..., bank=...,
status=..., created_at=..., updated_at=..., owner=..., currency=...)` in its own
body states nine facts, and typically only one of them is the thing under test.
The other eight are noise the reader must scan past to find the interesting
field, and every one of them has to be revisited when the model gains a required
column — across every test that spells the object out. A builder or factory with
defaults collapses that to `build_beneficiary(status="frozen")`, which says what
the test is about.

Fires when ALL of these hold:

* the file is a test file, and the **nearest enclosing function** of the call is
  named `test_*`,
* and the call passes more than eight keyword arguments.

The nearest-enclosing-function guard is what makes this rule worth having rather
than noise. A blind sweep of both corpora found 113 kwarg-heavy constructions,
but 96 of them sit inside a module-level `_make_*`/`_build_*` helper — which is
precisely the factory this rule asks for, already written. Counting those would
have meant nagging at the well-factored code and rewarding the sloppy kind.
Scoped to calls directly in a test body, the population drops to 17.

The threshold is deliberately high. Eight keywords is well past the point where
a constructor call is self-explanatory, and it was chosen so the rule fires only
where the audited corpora showed a genuine builder was missing — in at least
three cases, all in one first-party store test module, the fix is a one-line
import of a `build_beneficiary` helper that already exists in that repo's
shared test-builders module.

Deliberately NOT flagged:

* **a callee constructed only once in the whole file.** The message promises
  "every other test repeats the same boilerplate" — so the rule now checks that
  premise instead of asserting it. A single construction of a domain model with
  many required fields has no duplication to extract, and telling the author to
  build a factory for one call site trades real ceremony for nothing. Found in
  a first-party review regression: removing one `# pyright: ignore` forced an
  observability test to build a real `Batch(...)` with 12 required fields — the
  only `Batch(` in the file — and the rule blocked CI over it. Two or more
  constructions of the same callee
  still fire: that is the shape a builder actually fixes.
* calls inside a fixture, a `_make_*` helper, or any non-test function — that is
  the factory, and it is allowed to be verbose exactly once,
* positional arguments — a call with many positionals is a different smell, and
  ruff's own rules already discourage it,
* `dict(...)` and literal dict displays — those are data, not a domain object,
  and naming their keys is the point rather than the problem,
* `<mapping>.update(...)` — the same data case one call further on. The keywords
  are mapping entries being spread, not constructor fields, so there is no
  object for a builder to build. A 2,657-file third-party sweep produced 14
  findings and the widest of them (29 keywords) was rich's
  `table.box.__dict__.update(top_left="a", top="b", ...)`, which relabels box
  characters wholesale.

## Implementation notes

### `_KwargHeavyVisitor`

Mirrors SARJ031's enclosing-function stack so a construction inside a
`_make_*` helper or fixture declared anywhere in the file is attributed to
that helper — the factory is allowed to be verbose.
