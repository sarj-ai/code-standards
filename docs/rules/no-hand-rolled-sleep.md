# `no-hand-rolled-sleep` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-hand-rolled-sleep.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Ban the hand-rolled promisified timer —
`new Promise((resolve) => setTimeout(resolve, ms))` — in favour of
`node:timers/promises`'s `setTimeout`, and ban the hand-rolled
`Promise.race` timeout arm in favour of `AbortSignal.timeout(ms)`.

This is not a style preference. The stdlib version takes an `AbortSignal`;
the hand-rolled one silently cannot be cancelled, so it is a capability loss:

  - A hand-rolled sleep holds a live Node timer for its full duration. There
    is no handle to clear, so a request that is aborted, a shutdown, or a
    `Promise.race` the sleep loses all still wait out the whole delay. The
    `node:timers/promises` form takes `{ signal }` and rejects promptly.
  - The `Promise.race([work, rejectAfter(ms)])` idiom leaks the losing arm the
    other way round: when `work` wins, the timer is never cleared and keeps
    the event loop alive until it fires. `AbortSignal.timeout(ms)` is the
    stdlib expression of the same intent with no orphan timer.

WHY A CUSTOM RULE — no enabled rule reports this position. Resolved with
`ESLint#calculateConfigForFile` against the shipped `eslint.strict.mjs`
(204 enabled rules before this one) and confirmed by linting a file
containing every shape below: the only report was an unrelated
`promise-function-async`. The nearby external rules were checked individually
and each covers a DIFFERENT shape:

  - `unicorn` 72.0.0 has no promisified-timer rule at all (341 rules; the
    timer/promise family is `explicit-timer-delay`, `prefer-abort-signal-any`,
    `prefer-abort-signal-timeout`, `prefer-promise-with-resolvers`,
    `prefer-promise-try`, `no-multiple-promise-resolver-calls`).
  - `unicorn/prefer-abort-signal-timeout` (available, not enabled) fires on
    `new AbortController()` + `setTimeout(() => c.abort(), ms)`. Run against
    the shape file it reported ONLY that line and not the `Promise.race`
    timeout arm. Worth enabling on its own merits; it is not this rule.
  - core `no-promise-executor-return` (available, not enabled) fires on the
    concise-arrow spelling only — it did NOT report the block-bodied
    `(resolve) => { setTimeout(resolve, ms); }` motivating case, nor the
    `function (resolve) { ... }` spelling. Its remedy is "add braces", which
    entrenches the hand-rolled sleep rather than replacing it.

The polling-loop shape (`while (!done) { await sleep(ms); }`) is deliberately
NOT implemented here: core `no-await-in-loop` is already enabled at `error`
and reports that exact position (2 reports on the shape file). 74 non-test
occurrences in the OSS corpus below would have been duplicate reports.

MEASURED (2026-07). OSS corpus, 15 repos (hono, tRPC, drizzle-orm, undici,
vitest, got, cal.com, documenso, dub, formbricks, midday, openstatus,
papermark, unkey, zod): 124 non-test `new Promise` + `setTimeout` sleeps and
22 non-test reject-flavoured race arms. Private corpus, 7 repos: 53 non-test
sleeps across 21 files (plus 18 in one-off scripts, 1 in a test) and 1 race
arm. 463 further OSS occurrences are in test files and belong to the already
enabled `@sarj/no-sleep-in-test-body`, which is why test files are skipped
here rather than double-reported.

FIRES ONLY on the exact idiom, which is what keeps false positives near zero:
a `new Promise` whose executor body is a SINGLE `setTimeout` call and whose
callback is the executor's own `resolve` (or `reject`) parameter, passed
directly or as a zero-argument `() => resolve()` forwarder.

DELIBERATELY NOT FLAGGED:
  - `setTimeout(() => resolve(value), ms)` — a delayed VALUE, not a sleep.
    Every such occurrence measured in the private corpus was the losing arm
    of a race that resolves to a fallback result; `AbortSignal.timeout` does
    not express that and `node:timers/promises` would change the semantics.
  - `setTimeout(resolve, 0)` — a macrotask yield, not a delay. The stdlib
    answer is `setImmediate`, a different fix; `@sarj/no-sleep-in-test-body`
    draws the same nonzero-literal line.
  - Any executor doing more than the one `setTimeout` call — capturing the
    handle for `clearTimeout`, wiring `signal.addEventListener("abort", ...)`,
    or attaching listeners. That code is already cancellable; it is the thing
    this rule asks for, so reporting it would be backwards.
  - A reject-flavoured arm NOT inside `Promise.race` / `Promise.any`. Alone
    it is a delayed rejection, and `AbortSignal.timeout` is not a substitute.
  - Test files (`@sarj/no-sleep-in-test-body` owns those, and is enabled),
    one-off scripts, and generated files. The generated exclusion is load
    bearing rather than hypothetical: the same vendored SSE client
    (`.../generated/core/serverSentEvents.gen.ts`) supplied the only hit in
    three separate private repos, and it is overwritten on every codegen run.

CLIENT MODULES ARE SKIPPED BY DEFAULT, and this is the single most important
option. A browser or React Native bundle cannot import `node:timers/promises`
and the web platform ships no equivalent, so the fix advice is impossible to
follow there. This is the common case, not an edge case: 42 of the 53 private
corpus sleeps (79%) are in `.tsx` components. Set `checkClientModules: true`
only in a tree where every file can resolve `node:` builtins. The RACE
message is reported in client modules regardless — `AbortSignal.timeout` is
available on the web platform, so that fix always applies.

## Evidence relocated from the source

### `if`

The single call an executor body consists of, or `null` when the body does
anything else. "Anything else" is the false-positive guard: a body with a
second statement is capturing the handle, wiring an abort listener, or
otherwise already doing the cancellable thing this rule asks for.

