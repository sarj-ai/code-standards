# SARJ047 `sleep-with-computed-arg-in-test` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_sleep_with_computed_arg_in_test.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

SARJ031 flags a nonzero *literal* `sleep()` in a test body and deliberately
exempts a computed argument, on the reasoning that `sleep(delay)` is a
configured wait passed in by the caller. That reasoning holds for a fixture or a
helper. It does not hold when the nearest enclosing function is the test itself:
`await asyncio.sleep(POLL_INTERVAL_SECONDS * 4)` is not configuration, it is a
hand-tuned guess that four poll intervals is "probably enough" for a background
task to progress. Under CI load it is the same nondeterministic race, with the
same fix — synchronise on the signal, wait on an `Event`, or poll the condition
with a deadline.

This rule closes exactly that gap and nothing more. Where SARJ031 requires a
nonzero numeric literal, this one requires an argument that is *not* a literal —
a name, attribute, arithmetic expression, or call. The two are disjoint by
construction, so no `sleep()` is ever reported twice.

Fires when ALL of these hold:

* the file is a test file,
* the call is `asyncio.sleep(...)` or `time.sleep(...)` (receiver is the bare
  name `asyncio` or `time`, matching SARJ031's shape),
* the first argument is not a numeric literal — SARJ031 owns that case,
* and the **nearest enclosing function** is named `test_*`.

The nearest-enclosing-function stack is inherited verbatim from SARJ031 and is
the critical guard. A `sleep(delay)` inside a nested fake coroutine declared in
the test (`_hang`, `_slow`, `mock_*`) deliberately simulates latency to exercise
a cancellation or timeout path — that is the intended use of a configured wait,
and because the check keys off the *nearest* function, such a helper is excluded
automatically.

Deliberately NOT flagged:

* `sleep(0)` and other numeric literals — SARJ031's territory,
* a computed `sleep()` in a fixture, helper, or any non-test function — the
  configured-wait reading applies there,
* `sleep()` reached through an aliased import (`from asyncio import sleep`) —
  the attribute-receiver shape is shared with SARJ031 so the two rules stay
  aligned, and a sweep of both corpora found zero occurrences of the bare-import
  spelling to justify widening it.

## Implementation notes

### `_ComputedSleepVisitor`

The stack is SARJ031's, unchanged: a `None` entry for a lambda, and only the
top consulted, so a configured wait inside a nested fake coroutine is
attributed to that coroutine and never fires.
