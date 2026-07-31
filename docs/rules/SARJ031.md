# SARJ031 `no-sleep-in-test-body` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_sleep_in_test_body.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

`asyncio.sleep(0.01)` / `time.sleep(1)` placed straight in a test function body is
the canonical flaky-test pattern: under CI load the fixed delay is nondeterministic
(too short → the awaited work has not finished; the test flakes), and it slows the
suite for no benefit. The fix is to synchronize on the actual signal — await the
awaitable, wait on an `Event`, or poll a condition with a timeout.

This is test-scoped and genuinely uncovered: ruff ASYNC251 only flags blocking
`time.sleep` inside an `async def`, and nothing flags `asyncio.sleep(nonzero)`.

Fires only on the exact shape:

* a call `asyncio.sleep(<arg>)` or `time.sleep(<arg>)` (receiver is the bare name
  `asyncio` or `time`),
* where `<arg>` is a **nonzero numeric literal** (`int`/`float` `ast.Constant`) —
  `sleep(0)` is a cooperative yield, not a timing hack, and a non-literal
  `sleep(delay)` is a deliberate configured wait, so both are skipped, and
* whose **nearest enclosing function is a `test_*`-named** `def`/`async def`.

Critical false-positive guard: the sleep must sit DIRECTLY in the test body, with
no intervening nested `def`/`async def`/`lambda`. A sleep inside a nested helper /
fake coroutine declared within the test (`_hang`, `_slow`, `mock_*`) deliberately
simulates latency to exercise cancellation/timeout paths — that is the intended
use, not a flaky sync, and it must not fire. Because the check keys off the
*nearest* enclosing function, such a nested helper (not `test_*`-named) is excluded
automatically.

A sleep inside a `while` loop is also exempt: `while not cond: time.sleep(0.01)`
is condition-polling — exactly the remedy this rule's own message prescribes
(trio's OS-thread waits were the sweep case). Only a bare fixed delay flakes.

A bounded `for` retry loop that exits early on the condition is the same remedy
with a deadline attached, so it is exempt too:

    for _ in range(20):
        if started.is_set():
            break
        await asyncio.sleep(0.01)

The `for` must carry that conditional exit (an `if` whose body `break`s /
`return`s / `raise`s); a `for` that merely repeats a fixed delay each iteration
is not polling and still fires. Found in a 2,657-file third-party sweep against
anyio's `test_from_thread.py` (`for _ in range(10): if ...: return; sleep(0.1)`)
and black's `test_blackd.py` (`for _ in range(20): if started.is_set(): break;
await asyncio.sleep(0.01)`) — both poll with a timeout and neither can flake the
way a bare delay does.

Applies only in test files (stem `test_*.py`, `*_test.py`, `conftest.py`, or a path
under a `tests`/`test` directory).

## Implementation notes

### `_SleepInTestBodyVisitor`

Maintains a stack of enclosing-function names (`None` for a lambda, which has
no name and can never be a test). Only the top of the stack — the nearest
enclosing function — is consulted, so a sleep inside a nested helper/fake
coroutine declared within a test is attributed to that helper, not the test,
and does not fire.

### `_is_poll_loop`

`for _ in range(20): if ready(): break; sleep(0.01)` is condition-polling with
a deadline — the remedy this rule prescribes — so its sleep is not a flake.
A `for` body with no conditional exit merely repeats a fixed delay and is not
polling.
