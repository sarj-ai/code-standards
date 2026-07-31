# `no-conditional-in-test` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-conditional-in-test.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Disallow conditional logic in a test body, where it can hide an
assertion that never runs.

The rule only looks inside the callback of an `it` / `test` call. Conditionals
in `describe` bodies, in `beforeEach` / `beforeAll`, and in helper functions
declared inside a test are deliberately NOT reported — those are setup and
factory code, not the assertion path.

## Measurement

A seeded random read of 50 of the rule's 2,344 findings across 17 repositories
(6 first-party, plus zod, trpc, dub, openstatus, formbricks, documenso, unkey,
midday, papermark, cal.com, hono) put the false-positive rate at 84%. The
false positives fell into four shapes, each of which is now exempt. In every
one of them the conditional cannot hide an assertion, which is the entire
hazard the rule is about.

  1. **Narrowing guard pinned by the assertion above it** — 1,097 of 2,344
     (46.8%), 22 of the 50 read. `expect(r.success).toBe(false); if (!r.success)
     { expect(r.error...) }`. The `if` is a tax paid to the type checker, not a
     branch: had the discriminant gone the other way the PRECEDING assertion
     would already have failed, so the guarded assertions cannot be silently
     skipped. Exempt when the immediately preceding statement is an
     `ExpressionStatement` containing an `expect(...)` whose argument has the
     same root identifier as the `if` test.
     e.g. `zod/packages/zod/src/v4/classic/tests/union.test.ts:32`,
     `formbricks/apps/web/modules/api/v2/auth/tests/authenticate-request.test.ts:64`.
     Recall cost: the UNPINNED form still fires, and that is the shape worth
     firing on — `zod/packages/zod/src/v4/classic/tests/transform.test.ts:80`
     guards a `safeParse` result with no assertion above it, so the whole test
     passes vacuously when the parse unexpectedly succeeds.

  2. **An assertion spelled as a throwing guard** — 223 (9.5%).
     `if (!fetcher) throw new Error("fetcher missing")` is a failure, not a
     branch: the test cannot continue past it. Exempt when the consequent is
     (a block containing only) a `throw` and there is no `else`.
     e.g. `openstatus/packages/status-fetcher/__tests__/integration.test.ts:205`,
     `hono/src/helper/streaming/sse.test.tsx:381`.

  3. **`??` / `||` defaults** — 268 (11.4%). `data.monitors || []`, `code ?? ""`
     in fixture construction is a default value, not control flow over an
     assertion. `??` no longer reports at all; `&&` / `||` report only when the
     logical expression is the whole of an `ExpressionStatement` and its right
     operand contains an assertion — i.e. the `a && expect(a).toBe(1)` shape,
     which really can skip an assertion.
     e.g. `openstatus/apps/server/src/routes/v1/monitor/__tests__/monitor.test.ts:1979`,
     `cal.com/apps/web/playwright/oauth-provider.e2e.ts:561`.

  4. **Type-level narrowing** — `hono/src/types.test.ts` alone contributes 150,
     all `if (res.status === 200) { expectTypeOf(await res.json()).toEqualTypeOf<...>() }`.
     `expectTypeOf` / `assertType` are erased at run time, so a branch around
     them cannot skip anything that executes. Exempt when every statement in
     the consequent is such a call.

  5. **State normalization with no assertion and no escape** — 249 (10.6%).
     `if (json.error.data.stack) { json.error.data.stack = "[redacted]"; }`
     before a snapshot (`trpc/packages/tests/server/adapters/standalone.test.ts:252`).
     There is no assertion inside to skip and no way out of the test. Exempt
     ONLY when the branch contains neither an assertion nor `return` /
     `continue` / `break` / a `.skip(` call.

That last carve-out is load-bearing. Without it the rule loses its best true
positives, which are exactly the branches that ESCAPE the test:
`formbricks/packages/cache/src/cache-integration.test.ts:536`
(`if (!isRedisAvailable) { logger.info("Skipping..."); return; }` — the test
reports success having asserted nothing) and
`cal.com/apps/web/playwright/reschedule.e2e.ts:288`
(`if (!locationVideoCallUrl) return;`, which upstream itself annotates
`// FIXME: This should be consistent or skip the whole test`). Both are pinned
as `invalid` fixtures below, as is the unpinned narrowing guard from (1).

Measured over the same corpus after the change: 2,344 -> 359 findings (1,985
suppressed, 84.7%). `hono/src/types.test.ts` alone drops from 150 to 0, all of
it shape (4). Spot-checked recall on the cited files: the three true positives
above still report at exactly those lines, and the five false-positive sites
are silent.

## Evidence relocated from the source

### `isExemptIfStatement`

Guard 5 — state normalization. The branch has no assertion to skip and no way
out of the test, so it cannot hide anything. Deliberately narrow: a branch
that returns, breaks, continues, or calls `.skip(` is exactly the true
positive this rule exists for and is NOT exempt.

