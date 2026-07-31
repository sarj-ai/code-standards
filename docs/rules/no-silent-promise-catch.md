# `no-silent-promise-catch` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-silent-promise-catch.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Flag `.catch()` handlers that silently swallow the rejection:
`promise.catch(() => null)` and friends. These are the promise-chain twin of
the empty-`catch`-block anti-pattern already covered by the try/catch rules —
the failure vanishes with no log, no metric, no rethrow, and the caller
receives a sentinel it usually cannot distinguish from a real value.

Only handlers that provably do nothing are flagged: an arrow/function whose
entire body is a bare literal (`null`, `undefined`, a number, a string, a
boolean), an empty object/array literal, an empty block, or a block that
only `return`s one of those. A handler that references its error parameter
or calls anything (logging, metrics, rethrow) is never flagged.

Two corpus-driven exemptions (5-repo sweep, 2026-07: 11/35 raw hits — 31% —
were these deliberate idioms):
  - `res.json().catch(() => ({}))` / `res.text().catch(() => '')` — the
    body-parse-fallback idiom while composing error diagnostics; the parse
    failure itself is not the signal being handled.
  - Test files (`.test.` / `.spec.` / `__tests__/`), where silencing a
    promise is routine unhandled-rejection suppression.

A SECOND SWEEP (2220 files across zod / TanStack Query / react-router / swr /
zustand, 2026-07) produced 16 hits, of which 11 were false positives in three
families. All three are now exempt:

  - **Documented on purpose.** The handler body (or the line above / beside
    the call) carries a comment explaining the suppression. The rule's
    complaint is that the decision is invisible; a comment is exactly the
    thing that makes it visible, and the author has already answered.
    `query/packages/query-core/src/thenable.ts:54`
    (`thenable.catch(() => { /* prevent unhandled rejection errors */ })`) and
    `react-router/packages/react-router/lib/router/router.ts:6052-6053`
    (`// Prevent unhandled rejection errors - handled inside of \`callLoadOrAction\``
    directly above `lazyRoutePromise.catch(() => {})`) are the shape: the
    promise is ALSO consumed by the real handler, and this `.catch` exists only
    to stop the runtime's unhandled-rejection warning. 7 of the 16 hits.
  - **The chain continues.** `p.catch(() => null).then(…)` — the sentinel is
    consumed by the very next link, which IS the recovery, so no caller ever
    receives an indistinguishable value.
    `react-router/integration/helpers/playwright-fixture.ts:318`.
  - **Teardown calls.** `.cancel()` / `.close()` / `.abort()` / `.destroy()` /
    `.dispose()` / `.unlock()` reject when the resource is already gone, which
    is the outcome the caller wanted; the rejection is not the signal, exactly
    as for the `res.json()` fallback above.
    `react-router/packages/react-router/lib/rsc/html-stream/server.ts:80`
    (`await rscReader.cancel(reason).catch(() => {})`, inside the stream's own
    abort path). 3 of the 16 hits.
