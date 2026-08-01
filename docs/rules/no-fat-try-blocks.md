# `no-fat-try-blocks` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-fat-try-blocks.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Disallow `try` blocks whose body contains more than three
top-level statements that can throw (TS port of Python's SARJ007).

A fat `try` body obscures which statement is actually expected to throw and
widens the blast radius of the `catch` handler: unrelated failures get caught
(and often swallowed or mis-reported) by a handler written for a different
operation. Keep the `try` skinny — isolate the throwing statement(s) and move
the non-throwing setup and follow-up work outside.

Only top-level statements that can *throw* are counted. What counts, and the
guards that keep the count aligned with intent (tuned against ~5.6k real TS
files to drive false positives to ~zero):

  - An `await` always counts — awaiting a promise is the canonical throwing
    operation in async TS. A statement with an `await` in its same-scope
    subtree counts.
  - A synchronous call / `new` whose value is *used* (assigned, returned,
    branched on, or passed as an argument) counts — e.g. `const x = parse(s)`,
    `return build(x)`, `if (!validate(x))`.
  - A bare fire-and-forget call statement with no `await` does NOT count. In
    idiomatic TS these are side effects — React state setters (`setOpen(false)`),
    toasts (`toast.error(...)`), `router.refresh()`, logging, optional
    callbacks (`onSuccess?.()`). They are the post-success UI work that
    naturally trails the one awaited action; counting them flagged nearly
    every event handler. The exemption is applied STRUCTURALLY, recursing
    through blocks and `if`/`else` branches, so wrapping the same call in a
    guard (`if (!res.ok) { logEvent("http_error", { path }); return null; }`)
    does not resurrect it. A guard's TEST is still examined — a call whose
    result is branched on (`if (!validate(x))`) still counts.
  - Pure, non-throwing array / string / `Map` / `Object` / `Math` / `JSON`
    helpers (`.map`, `.filter`, `.push`, `.get`, `.join`, `Object.keys`, ...)
    do NOT count — they are data plumbing, not the operation being guarded.
  - Calls inside a nested function / arrow body do not run when the `try`
    executes, so they are not counted (same-scope walk).

Two structural exemptions match the Python rule:

  - A `finally` clause is a deliberate cleanup contract that couples the body
    to the handler — exempt.
  - A `catch` handler guaranteed to re-throw (its body's last statement is a
    `throw`) makes the wide body uniform error-context wrapping, not an
    over-broad swallow — exempt.

## Terminal error-propagating boundary (measured)

A seeded random read of 45 of the rule's 801 findings across 17 repositories
(6 first-party, plus zod, trpc, dub, openstatus, formbricks, documenso, unkey,
midday, papermark, cal.com, hono) put the false-positive rate at 77.8%, and
all 35 false positives were a single class: the `try` is the *tail* of the
function and the handler converts any failure inside it to one uniform error
result — `catch (e) { return handleAndReturnErrorResponse(e) }`,
`catch (e) { toConnectError(e) }`,
`catch (e) { logger.error(...); return err({ type: "internal_error" }) }`.
Nothing can be mis-attributed, because the handler never asks which statement
threw. That is exactly the reasoning the re-throw exemption above already
applies; it simply stopped at `throw` and never considered the HTTP / RPC /
`Result`-type equivalent of re-throwing. Representative:
`dub/apps/web/app/(ee)/api/cron/fx-rates/route.ts:12`,
`openstatus/apps/server/src/routes/rpc/handlers/maintenance/index.ts:102`.

The exemption therefore requires ALL of:

  a. the `try` is terminal — nothing in the enclosing function runs after it
     (it is last in its block, and every enclosing block up to the function
     boundary is likewise last; a loop or `switch` in between disqualifies);
  b. the handler's last statement is a `return`, a `throw`, or a bare call —
     the handler ends by handing the failure off, it does not fall through
     into more work;
  c. the handler mentions the caught binding, so the failure is actually
     reported rather than discarded;
  d. the handler never returns a bare `null` / `undefined` / `false` / `[]` /
     `{}` — that is the success-shaped swallow the rule exists to find, and it
     turns a fat body into "some unknown one of these five operations failed,
     and the caller sees an empty result".

Measured over the same corpus: 801 -> 175 findings (626 suppressed, 78.2%).
The surviving 175 are a strict subset of the original 801 — the exemption
introduces no new reports anywhere in the corpus. Recall cost was zero against
the read sample: each of its true positives survives via a different clause,
and each is pinned as an `invalid` case below —
`midday/apps/api/src/rest/routers/apps/slack/messages.ts:81`, a handler that
inspects the error and falls back to another transport (fails b);
`midday/packages/banking/src/providers/enablebanking/enablebanking-api.ts:404`,
a handler that resets state before the function retries with another strategy,
so the `try` is not terminal (fails a); and
`cal.com/packages/app-store/salesforce/lib/CrmService.ts:550`, a nine-statement
body whose handler logs and returns `[]`, silently turning a configuration bug
into "no contacts found" (fails d). All three still report after the change.

## On the threshold — do not reach for it

`MAX_TRY_BODY_STATEMENTS` is 3 and should stay 3. Body-size counts over all
801 findings were 4 -> 228, 5 -> 121, 6 -> 112, 7 -> 78, 8 -> 53, tailing to
27, median 6. Raising the threshold to 5 removes 44% of the volume *uniformly*
across true and false positives — it trades recall for quiet without making
the rule any more correct. The shape of the handler, not the size of the body,
is what separates the two populations.

## `JSON.parse` was on the "pure, non-throwing" list

`PURE_NAMESPACES` held `JSON`, and the rule's own prose called the JSON helpers
"pure, non-throwing". `JSON.parse` is the canonical throwing call in JavaScript
and the canonical reason anybody writes `try`/`catch` at all, so the one shape
this rule most needed to see was the one it could not.

Reproduced: four `JSON.parse` calls in a `try` with a swallowing `catch`
produced **0** reports; the identical shape written with `parseA()` reported
correctly.

`JSON.stringify` also throws — circular structures, `BigInt` — but is
overwhelmingly called on a value the same function just built, so it stays pure.
That is a recall choice, stated rather than hidden.

## `PURE_METHODS` matched by method NAME alone

`get`, `set`, `add`, `delete`, `has`, `clear`, `find`, `keys`, `values` and
`entries` are the `Map` / `Set` API. They are also `client.get(url)`,
`redis.set(k, v)`, `repo.find(where)`, `api.delete(id)` and `bucket.has(key)` —
every one of which does network or disk I/O and throws. A name-only test cannot
tell those apart, and it resolved the ambiguity towards "pure", which is the
unsafe direction for a rule whose entire job is to find over-broad `catch`
handlers. Four `client.get`-shaped statements in a `try` with a swallowing
`catch` produced **0** reports.

Those names are out of the name-only set. What remains are Array / String /
Number members with no I/O reading: nothing calls `.padStart()` on a database
handle. The failure mode of what is left is a false NEGATIVE (a genuine array
method on a receiver that also does I/O), not a false negative on the exact
swallow the rule exists to catch.

`isBareCallStatement` continues to exempt fire-and-forget `cache.set(k, v);`
statements structurally, which is the common non-I/O use of the removed names —
pinned as a `valid` case so the change did not resurrect that false-positive
class.

Corpus effect: 277 -> 315 findings over 32 OSS TypeScript repos / 145,235 files
(+13.7%), of which the scoping restoration in `_paths` is a part.
