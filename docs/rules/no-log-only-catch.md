# `no-log-only-catch` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-log-only-catch.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Disallow `catch` clauses that only log (via `console.*` or a
logger receiver such as `logger.warn(...)` / `Log.error(...)`) and then
swallow the error. A catch that logs and falls through — with no `throw`, no
`return`, and no real recovery — hides failures: the program keeps running in
a broken state while the only signal is a log line that is easy to miss.
Either rethrow the error or handle it for real.

This rule is deliberately conservative and fires in exactly two shapes:
  - `noLogOnlyCatch`: the catch body is non-empty and *every* statement is a
    logging call (`console.*` or a call on a logger-named receiver). Any other
    statement (a `throw`, a `return`, a fallback assignment, a non-logging
    call, etc.) means the catch is doing something and is left alone.
  - `emptyCatch`: the catch body is genuinely empty AND carries no comment.
    A comment-only catch (`catch { /* ignore, safe because … */ }`) is treated
    as an intentional, documented ignore and is exempt.

The documented-ignore exemption applies to BOTH message ids. A catch that logs
and explains why the failure is survivable is the same deliberate decision as
a comment-only empty catch, and the rule's own message ("handle it for real")
has nothing to add to it. Measured on 2,186 real TypeScript files (zod /
TanStack Query / react-router / swr / zustand): of 10 log-only hits, the one
carrying a written rationale was
react-router/packages/react-router-dev/vite/styles.ts:104 —
`catch { console.warn(...); // this can happen with dynamically imported
modules … }` — and it is precisely the case the rule should not litigate. A
bare `catch (e) { console.error(e); }` with no comment still fires (9 hits,
e.g. react-router/packages/react-router/lib/dom/ssr/fog-of-war.ts:209).

A previous version fired the "logging then swallowing" message on empty and
comment-only catches that contained no logging call at all — the vast majority
of real-world hits — which was factually wrong. The two distinct message ids
keep each diagnostic accurate.

Scope: this rule owns the `CatchClause` (try/catch) form ONLY. The promise
form — `.catch(() => {})`, `.catch(() => null)`, and every other handler that
provably does nothing — is owned entirely by `no-silent-promise-catch`, whose
detection is a strict superset of what this rule used to do there. Two rules
firing on one `.catch()` meant two messages and two suppression comments for
a single defect, so the promise path was removed from here.

A logging call is recognised by the shared `_logging` matcher: a log method on
a logger receiver, plus any project-declared free logging function named in
the `logFunctions` option (`logEvent("x", { err })`). Structured loggers are
usually free functions, so without that option a catch that only calls one was
silently under-reported here — declaring it makes the shape visible.

--- 2026-07 corpus audit (25,508 deduped TS/TSX files across 6 first-party
repos and zod / trpc / dub / openstatus / formbricks / documenso / unkey /
midday / papermark / cal.com / hono) -------------------------------------

780 findings (683 `noLogOnlyCatch`, 97 `emptyCatch`); 44 were read at random
and 15 of them (34.1%) were wrong. The three classes each get a guard here.

 1. `fallbackFollowsTry` — an empty catch whose recovery is the statement
    AFTER the try. 4 of the 44. `hono/src/middleware/timing/timing.ts:30` is
    the canonical shape: `try { return performance.now() } catch {} return
    Date.now()`. The error IS handled — by the fallback the `return` inside
    the try skips over — and an in-body comment cannot express that better
    than the code already does. Recall cost: an empty catch whose try does not
    end in a `return`, or which nothing follows, still fires.
 2. `seededFallbackHandled` — an empty catch over an assignment to a binding
    seeded with an explicit fallback one line above and read after the try
    (`let msg = "…"; try { msg = (await r.json()).error } catch {} send(msg)`,
    cal.com/packages/app-store/jelly/api/callback.ts:28). Bounded four ways so
    it cannot widen into "any catch near a `let`": the declaration must be the
    IMMEDIATELY preceding statement, must be a single non-`const` binding with
    an explicit seed value, must be written inside the try block, and must be
    read after it. A bare `let x;` with no seed is not a fallback and still
    fires.
 3. `hasAdjacentRationale` — the rationale comment sits next to the braces
    rather than inside them, so `getCommentsInside` never saw it. 4 of the 44,
    e.g. openstatus/packages/api/src/router/page.ts:70 ("best-effort: the page
    is gone either way, a leaked Vercel attachment is recoverable while a
    failed delete is not") and
    dub/apps/web/lib/actions/partners/program-resources/update-program-resource.ts:133.
    Both write the rationale above the `if` that guards the try, so the scan
    covers the line above the `try`, the line above the `catch`, and — only
    when the try is the SOLE statement of its block — the line above the
    enclosing `if`/loop. Recall cost is the same one the in-body exemption
    already accepts: an unrelated comment above a try exempts its catch.
 4. Path drift: the rule shipped its own `\.test\.` / `\.spec\.` /
    `__tests__/` list instead of the shared `_paths.isTestFile`, so the
    `*-spec.ts` and `*-test.ts` suffix conventions were not exempt — 16 of the
    780 sat in files this rule already meant to skip, e.g. a cal.com
    `*.e2e-spec.ts` teardown at line 1892. Delegating removes the drift at
    zero recall cost. A further 22 sat under a `benchmarks/` directory
    (`zod/packages/zod/src/v3/benchmarks/object.ts:45` is `try {
    short.parse(null) } catch (_err) {}`, an expected-throw harness); that
    segment is handled locally here because `_paths` does not yet know it.

DELIBERATELY still firing: 19 of the 44 were fire-and-forget boundaries —
telemetry (dub/packages/utils/src/functions/log.ts:47 is the logging helper
itself failing to reach Slack), analytics, cleanup, best-effort UI. Writing
one line saying so is cheap and makes the intent auditable, which is the whole
design of the documented-ignore exemption. The 10 unambiguous true positives
are worth the noise: cal.com/packages/app-store/zohocalendar/lib/
CalendarService.ts:77 returns stale expired credentials after a failed token
refresh, which is the exact failure mode the message describes.

## Evidence relocated from the source

### `slot`

True when some statement follows `node` once control leaves it — either in its
own statement list or in an enclosing one, stopping at the function boundary.
`try { return x } catch {}` inside an `if` is still guarded by the `return`
that follows the `if` (papermark/components/ui/timestamp-tooltip.tsx:41).

