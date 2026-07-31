# `no-sentinel-return-on-catch` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-sentinel-return-on-catch.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Disallow silently swallowing an error in a `catch` clause by
returning a "sentinel" empty value as the final/only statement.

A `catch` block whose last statement is `return null` / `return undefined` /
`return false` / `return []` / `return {}` (and which never `throw`s) discards
the caught error entirely. Downstream callers can't distinguish a genuine
empty result from a failure, which is a frequent source of silent data loss
and broken idempotency decisions.

This rule is deliberately conservative — it prefers false negatives over
false positives. It does NOT flag:
  - catch blocks that `throw`/rethrow anywhere in their body,
  - returns of a computed/meaningful value (calls, identifiers, member
    expressions, non-empty literals),
  - `return 0` / `return ""`, which are often legitimate results,
  - catches that LOG or REPORT the caught error before the sentinel return —
    a `console.*`/logger call, a project-declared free logging function (the
    shared `logFunctions` option), or an error-reporting call that mentions
    the caught binding ANYWHERE in its arguments. The binding search walks the
    whole argument subtree, because structured loggers take a meta object:
    `logEvent("x", { error: err instanceof Error ? err.message : String(err) })`
    reports the error just as surely as `report(err)` does. Here the sentinel
    is a deliberate degraded return, not a silent swallow.
  - the typed-optional / safe-parse / predicate shape: the try body returns an
    expression whose subtree contains a parse-style call that throws on bad
    input (`JSON.parse(x)`, `new URL(s).protocol === "https:"`, or a lone
    `await request.json()`), or the enclosing function is a predicate — either
    declared (`: boolean`) or NAMED as one (`isDirectory`, `fileExists`) — or
    returns the same sentinel kind on a normal path, including through a
    ternary (`return valid ? value : false`). Here the sentinel is the
    declared contract.

The predicate exemption is deliberately limited to a `boolean` result. A
declared `T | null` / `T | undefined` return does NOT exempt: hiding a
failure behind a nullable accessor is the exact true positive this rule
exists for, and exempting it would gut the rule.

The last two clauses came out of a 2026-07 corpus sweep (2220 files across
zod / TanStack Query / react-router / swr / zustand) in which the rule fired
10 times and every hit was a false positive — see `PREDICATE_NAME_RE` and
`returnedSentinelKinds` for the per-family evidence.

Scope: this rule owns the `CatchClause` (try/catch) form ONLY. The same
swallow written in promise form — `await load().catch(() => [])` — is owned
entirely by `no-silent-promise-catch`, whose detection (any handler that
provably does nothing: bare literal, empty collection, empty block, or a
block returning one of those) is a strict superset of the empty-collection
check this rule used to run there. Two rules firing on one `.catch()` meant
two messages and two suppression comments for a single defect, so the
promise path was removed from here.

## Evidence relocated from the source

### `(fn as unknown as { params: TSESTree.Parameter[] }).params.s`

"Read" means a VALUE position. A bare name match is not enough, and getting
that wrong silently guts the rule. Walking the whole argument subtree (so a
structured logger's meta object counts as reporting the error) cost 8 of 18
true positives when measured against the previous release, because all of
these matched on name alone:

### `if`

Corpus evidence (2220 files across zod / TanStack Query / react-router / swr /
zustand, 2026-07): 7 of the rule's 10 hits were unannotated predicates —
`react-router/packages/create-react-router/utils.ts:196-202` (`directoryExists`),
`:205-211` (`fileExists`), and
`react-router/packages/react-router/lib/rsc/server.rsc.ts:1501-1507`
(`isClientReference`). `false` is the ANSWER those functions exist to give;
there is no richer value a caller could have received.

### `only`

`JSON.parse` / `new RegExp` / `new URL` count from anywhere in the try body —
a read-then-parse (`const t = read(p); return JSON.parse(t)`) is still the
safe-parse contract. A body-decoding method (`.json()`) counts ONLY when it is
the try's sole statement, so `try { return await request.json() }` is exempt
while `try { const res = await fetch(url); return await res.json() }` is not:
there the catch also swallows the network failure, which is the true positive.

### `kinds.add(direct);`

Corpus evidence (2026-07 sweep): the remaining 3 of the rule's 10 hits were
this spelling —
`react-router/packages/react-router/lib/server-runtime/crypto.ts:30`
(`return valid ? value : false;` on the happy path, then `return false` in the
catch for an unparseable signature) and
`react-router/scripts/utils/git.ts:12` (`return typeof parsed.version ===
"string" ? parsed.version : null`). In both, the catch sentinel is the value
the function already documents for "no result", so it hides nothing.

