# `no-sleep-in-test-body` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-sleep-in-test-body.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

TS port of SARJ031 (`no-sleep-in-test-body`). A real timed sleep
placed directly in a test body — `await new Promise((r) => setTimeout(r, 50))`
or `await sleep(200)` — is the canonical flaky-test pattern. The delay is a
guess about how long some other work takes: too short and the test fails on a
loaded CI runner, too long and every run pays for it. Either way the test is
asserting on wall-clock time rather than on the signal it actually cares about.

The fix is to synchronize on the signal: await the promise the code returns,
await the flushed microtask queue, or drive time deterministically with
`vi.useFakeTimers()` + `await vi.advanceTimersByTimeAsync(ms)`, which makes the
elapsed time exact and the test instant.

Fires only on the exact shape:

- `new Promise(...)` whose executor body is a `setTimeout(resolve, <n>)`, or a
  call to a bare `sleep`/`delay`/`wait`/`pause` helper, where
- the delay is a **nonzero numeric literal** — `setTimeout(r, 0)` is a
  macrotask yield used to flush the event loop, not a timing guess, and a
  non-literal `sleep(configuredDelay)` is a deliberate parameterised wait, and
- the **nearest enclosing function is the callback of an `it`/`test`** (any
  `.only`/`.skip`/`.each` variant) or of a `beforeEach`/`afterEach` hook.

The nearest-enclosing-function gate is the critical false-positive guard, and
it is ported deliberately: a sleep inside a nested helper or fake declared
within the test (`const slowFetch = async () => { await sleep(50); ... }`) is
*simulating* latency in order to exercise a timeout or cancellation path. That
is the intended use of a delay in a test, not a flaky synchronization, and it
must not fire. Because the check keys off the nearest enclosing function, such
a helper is excluded automatically. The `new Promise` executor arrow is not
treated as an enclosing function — it is part of the sleep idiom itself.

Applies only in test files.
