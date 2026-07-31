# `prefer-module-level-schema` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/prefer-module-level-schema.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Flag a Zod schema built INSIDE a function body when nothing in
that function is part of it. The schema is rebuilt from scratch on every
call, every request, every render.

This is the Zod sibling of `prefer-module-level-constant`, and it exists
because that rule cannot reach here by construction: its hoist gate requires
every leaf of the initializer to be a LITERAL, and `z.object({ id:
z.string() })` is a call expression, so a schema never satisfies it. The two
rules are disjoint and share one rationale, in increasing order of severity:

1. Allocation. A Zod schema is not a literal — `z.object({...})` walks the
   shape, constructs a `ZodObject` plus one schema instance per key, and
   caches nothing. Doing that per request in a route handler, or per property
   read in a getter, is pure waste that a single hoist removes forever.
2. Identity churn. A fresh schema object every render is a fresh reference
   every render, which silently defeats `useMemo`/`useEffect` dependency
   arrays and any resolver (`zodResolver`, `react-hook-form`) that compares
   schema identity to decide whether to re-validate.
3. Discoverability. A schema buried in a function body cannot be exported,
   tested, reused, or `z.infer`-ed from. The next function that needs the
   same payload gets its own copy, and the copies drift — which is the defect
   `prefer-zod-infer` and `zod-naming-convention` also exist to prevent.

WHAT FIRES — a call to one of the `factories` (default: the object-like
composites, see below) that sits inside a function and whose ENTIRE subtree
is free of anything the function owns. That last clause is the whole rule:
it is what makes "move this to module scope" provably correct rather than a
guess.

DELIBERATELY NOT FLAGGED, each an FP class that was measured, not imagined:

  - **It closes over a parameter, local, type parameter, or local type.**
    `function envelope<T extends z.ZodTypeAny>(inner: T) { return z.object({
    data: inner }) }` is a schema FACTORY, not a misplaced constant; hoisting
    it is a compile error. Resolved through the scope manager, so a TYPE
    reference counts too — `z.custom<Inner>()` where `Inner` is declared in
    the function body pins the schema there just as firmly as a value would.
  - **It reads `this` / `super` / `arguments`.** A schema inside a getter that
    splices in `this.base` belongs to the instance. Verified against a
    fixture rather than assumed: the free-variable check alone says
    `get s() { return z.object({ a: this.base }); }` is hoistable, and it is
    not, so `this` is a separate bail.
  - **It is already memoized** — wrapped in `useMemo`, `memo`, `once`, or
    `lazy`. The cost the rule is about has already been paid once.
  - **It is nested inside another Zod call.** Only the OUTERMOST factory in an
    expression is reported, so `z.array(z.object({...}))` is one finding, not
    two, and the `z.lazy(() => z.object({...}))` recursion idiom — whose
    callback exists precisely so the schema is NOT built eagerly — is never
    reported at all.
  - **An object schema with fewer than `minProperties` keys.** `z.object({})`
    as a placeholder shape, or a one-key `z.object({ reason: z.string()
    }).parse(body)` written inline at its only use, reads better where it is.
    `dub/apps/web/lib/ai/create-support-ticket.ts:28` (`inputSchema:
    z.object({})`) is the empty case; the default of 1 excludes it.
  - **Test files** (`ignoreTestFiles`, default true) and **generated files**.
    A schema inside a `describe` block is fixture data that belongs next to
    the assertion, and codegen re-emits its own layout on every run.

`z.array` and `z.enum` are NOT in the default `factories` list even though
they measured 138 and 28 more hoistable hits. They are thin wrappers around
an already-built schema or a literal list; the allocation argument is much
weaker and the reports are mostly noise. Repos that want them can say so:
`{ factories: ["object", "array", "enum"] }`.

NO AUTOFIX, for the same reason `prefer-module-level-constant` has none:
hoisting must choose an insertion point, may collide with an existing
module-scope name, and — where the schema references a module constant
declared BELOW the function — must also reorder the module to avoid a TDZ
error. All three are judgement calls, and a wrong automated hoist is worse
than a warning.

MEASURED, rule as shipped, over 30,546 .ts/.tsx files in 17 repos (7
first-party plus zod, trpc, dub, openstatus, formbricks, documenso, unkey,
midday, papermark, cal.com); 3,644 of those files import Zod.

  378 reports, in 12 of the 17 repos — openstatus 211, midday 60, unkey 30,
  formbricks 23, papermark 19, cal.com 18, dub 9, trpc 1, zod 1, plus 6
  across two of the seven first-party repos and 0 in the other five.

The chain walk is worth 7 of those 378 on its own: reporting over the
`z.object` node alone produced 385, and the 7 extra were schemas whose
`.superRefine` / `.catch` argument closed over a parameter. Every one of them
is now a `valid` case in the tests.

Public examples, read in full and confirmed:
  - `openstatus/packages/tinybird/src/client.ts` — 211 in one file, each
    inside a `public get pipeName()` accessor, so two `z.object`s are rebuilt
    on every property READ.
  - `unkey/web/internal/clickhouse/src/telemetry.ts:7` — `schema: z.object({
    request_id, time, runtime, platform, versions })` inside
    `insertSDKTelemetry(ch)`, rebuilt per insert.
  - `cal.com/packages/trpc/server/routers/viewer/admin/createCoupon.handler.ts:75`
    — `const schema = z.object({ promotionCode, couponId })` rebuilt per
    request and used once, on the next line.
  - `cal.com/apps/web/components/settings/SecondaryEmailModal.tsx:34` —
    `zodResolver(z.object({ email: emailSchema }))` in a component body: a
    new schema AND a new resolver on every render, cost 2 above.
  - `papermark/app/(ee)/api/workflows/[workflowId]/steps/route.ts:39,155,353`
    — the SAME `z.object({ workflowId, teamId })` written out three times in
    one file, once per handler. Cost 3, made literal.

External coverage was checked before this rule was written, not after.
`ESLint#calculateConfigForFile` against the shipped `eslint.strict.mjs`
resolves 204 enabled rules; a fixture holding this exact pattern drew zero
reports from all of them — `prefer-module-level-constant` and
`unicorn/consistent-function-scoping` included. `eslint-plugin-zod@4.9.0`,
whose `prefer-nullish` and `no-any-schema` this change enables outright, has
no rule in this area either.

## Evidence relocated from the source

### `parent.type === AST_NODE_TYPES.MemberExpression &&`

This is load-bearing, and it was a measured false positive before it existed.
`documenso/apps/remix/app/components/dialogs/sign-field-checkbox-dialog.tsx:32`
is `z.object({ values: ... }).superRefine((data, ctx) => { ...fieldMeta... })`
inside a component — the `z.object` subtree closes over nothing, but the
`superRefine` callback reads a component PROP, so the schema cannot move. The
free-variable check has to see the callback, which means it has to run over
the chain rather than over the factory call alone.

### `}`

True when some ancestor between `node` and module scope already accounts
for this schema: a REPORTABLE Zod factory (so one expression yields one
finding, anchored at its outermost reportable node), or a memo wrapper
(`useMemo`, `memo`, `once`, `z.lazy`) that already pays the cost once.

A Zod call that is NOT a reportable factory does not cover, which is what
keeps `z.array(z.object({...}))` reportable under the default options:
`z.array` is excluded from `factories`, and swallowing the `z.object`
inside it would silently drop the finding entirely.

## Why `prefer-module-level-constant` cannot reach a schema

Its hoist gate requires every leaf of the initializer to be a LITERAL, and
`z.object({ id: z.string() })` is a call. Measured over the same 17-repo corpus:
1,885 factory calls sit inside a function, 596 in non-test non-generated source,
and the free-variable / `this` gates hold back the 82 that close over something
the function owns.
