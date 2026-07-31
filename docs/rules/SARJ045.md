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

## 2026-07 false-positive audit

Measured on a 12-repo corpus: **2,064 findings**. A seeded random sample of 50
read against source put the false-positive rate at **20%**. The two guards below
removed **365 of 2,064 (17.7%)**, taking the rule to **1,699**.

* **A mock assertion — a callee named `assert_*`.** Nothing is constructed, and
  "extract a helper with defaults" is the *opposite* of what the call wants: the
  assertion exists to pin the exact, complete call the code under test made, so
  hiding its keywords behind a default-carrying helper would delete the thing
  being asserted. The repetition premise was also satisfied spuriously here,
  because `_callee_name` collapses a dotted path to its last segment and every
  unrelated mock in the file then votes for every other one. **276 of 2,064
  (13.4%)**, and reading a seeded random sample of them turned up **no true
  positive**. Only three names occur corpus-wide — `assert_called_once_with`
  (268), `assert_called_with` (4), `assert_awaited_once_with` (4) — none of which
  can construct anything, so the guard is exact rather than heuristic. It also
  repaired 88 of the 104 spurious-repetition findings for free. The sharpest
  single case: one third-party operator test flagged the 12-keyword
  `mock.assert_called_once_with(...)` while leaving the genuine 12-keyword
  `ListHyperparameterTuningJobOperator(...)` sixteen lines above it alone, because
  that construction was unique in the file. The rule was firing on the assertion
  and missing the construction.
* **A call to a function this module defines** — `node.func` is a bare `Name`
  bound to a `def` in the same file. That callee IS the helper this rule asks for:
  a factory, a fixture-factory, or a shared assertion helper whose keywords are
  the parametrized case matrix. The exemption above covers calls made *inside*
  such a helper; without this one the rule nags at calls *to* one, which is
  already-refactored code. **89 of 2,064 (4.3%)** across 9 distinct callees, every
  one a factory, fixture or assertion helper, and no true positive among them.
  Bounded on purpose: a callee the module does not define is a domain type
  imported from production code and still fires.

**The message was reworded from "builder" to "helper".** The largest remaining
ARGUABLE class — roughly a third of what is left — is a test invoking the system
under test with its full parameter list. That is deliberately still reported: the
duplication complaint is correct there, the words just have to fit.

**Deliberately NOT implemented, having been measured:** counting repetitions by
the full dotted path rather than the trailing attribute. The miscount is real, but
88 of the 104 findings it affects are mock assertions that the `assert_*` guard
already removes, and the incremental 16 include true positives.

## Implementation notes

### `_KwargHeavyVisitor`

Mirrors SARJ031's enclosing-function stack so a construction inside a
`_make_*` helper or fixture declared anywhere in the file is attributed to
that helper — the factory is allowed to be verbose.
