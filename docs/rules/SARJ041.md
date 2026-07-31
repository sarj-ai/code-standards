# SARJ041 `test-loops-over-literal-cases` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_test_loops_over_literal_cases.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

`for payload in [a, b, c]: assert f(payload)` is `@pytest.mark.parametrize`
written by hand, and it loses everything the decorator provides. The loop is one
test to pytest, so it **stops at the first failing case** — a change that breaks
four of the six cases reports as a single failure and hides the blast radius.
The cases get no ids, so the run output names the loop's test, never the case.
And a case cannot be xfailed, skipped, or selected with `-k` individually.
Promoting the table to `@pytest.mark.parametrize` turns N hidden cases into N
independently reported tests for free.

Fires when ALL of these hold:

* the file is a test file, and the **nearest enclosing function** of the loop is
  named `test_*` — a loop inside a fixture or a local helper is building data,
  not enumerating cases, and the nearest-function check (the SARJ031 technique)
  excludes it automatically,
* the loop iterates a **literal** `list`, `tuple`, or `set` displayed inline at
  the loop header, holding at least two elements,
* the loop body contains an `assert` (at any depth inside the loop, but not
  inside a nested `def`),
* and the body does **not** open a sub-test context.

The literal-iterable requirement is the load-bearing false-positive guard, and
it is the entire difference between this rule and a naive "assert inside a for"
check. A blind sweep of both production corpora found 144 loops containing an
assert but only 48 iterating a literal; the 96-loop difference is dominated by
**exhaustiveness checks** — `for member in Language:`, `for name in ProbeName:`,
`for row in await store.list_calls():` — which iterate an enum, a fixture, or a
query result. Those express a single universal-quantifier behaviour ("every
member has a template"), not a table of independent cases; parametrizing them
would be wrong, and flagging them would have put this rule near a 67% false
positive rate.

Deliberately NOT flagged:

* `for i in range(n)` — a repetition count, not a case table. `range` is a call,
  so the literal check already excludes it,
* iteration over a name, attribute, comprehension, enum, or any call result —
  the cases are not visible at the loop header, so there is nothing to lift into
  a decorator,
* a single-element literal — no table to speak of,
* a literal loop whose body only builds state or calls the system under test
  with no assertion — that is setup, and setup legitimately loops,
* **a loop that wraps each iteration in a sub-test** — `with self.subTest(...)`
  (unittest) or `with subtests.test(...)` (the pytest-subtests plugin). Every
  complaint in the message above is already answered there: the loop does not
  stop at the first failure, and each iteration is reported under its own named
  sub-test. `black/tests/test_black.py:1699` and `:1719` iterate
  `["include", "force-exclude"]` inside `with self.subTest(config_key=...)`;
  both were third-party-sweep false positives.

## Implementation notes

### `_LiteralCaseLoopVisitor`

Mirrors SARJ031's enclosing-function stack: only the innermost function is
consulted, so a case loop inside a helper or fixture declared within a test
is attributed to that helper and never fires.
