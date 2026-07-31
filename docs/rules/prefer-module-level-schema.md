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
    z.object({})`) is the empty case. The default is 2, so BOTH are excluded;
    it was 1 for a while, which excluded only `z.object({})` while this list
    promised otherwise, and that gap was 33.8% of the rule's output.
  - **It renders text in the active locale.** A tagged template, a call to
    `t` / `$t` / `msg` / `translate` / `gettext`, or a method on `i18n` /
    `intl` inside the schema means the message is built when the factory runs,
    after `i18n.activate(...)`. Hoisting it freezes every validation message in
    the boot locale — a behaviour change, not a refactor, and the one class here
    where following the advice makes the program WRONG.
  - **It is a fragment of a schema that cannot itself move.** Reporting is
    anchored at the outermost enclosing Zod construct, `.extend(...)` /
    `.merge(...)` / `z.preprocess(...)` / `z.array(...)` included. When that
    outer expression closes over the function, prising one key's value out of it
    to module scope saves nothing: the object literal around it is rebuilt per
    call regardless.
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


## 2026-07-31 re-audit — three defects, one of them a correctness bug

Re-measured over a second, disjoint corpus: **105,551 `.ts`/`.tsx` files across
63 OSS repositories**, of which 2,517 mention Zod. **219 findings as previously
shipped, 145 now.**

### 1. The rule advised a change that BREAKS i18n

`twenty/packages/twenty-front/src/modules/auth/sign-in-up/hooks/
useTwoFactorAuthenticationForm.ts:7`:

```ts
import { t } from '@lingui/core/macro';

const createOtpValidationSchema = () =>
  z.object({ otp: z.string().trim().length(6, t`OTP must be exactly 6 digits`) });
```

`t` is a Lingui macro and the zero-argument factory exists precisely so the
message is rendered AFTER `i18n.activate(locale)`. `closesOverNothing` skips
`ImportBinding` definitions, so `t` was invisible and the rule advised a hoist
that freezes every validation message in whatever locale happened to be active
at module-eval time. Shipped at `error`. This is the only class here where
following the rule makes the program wrong rather than merely noisier.

Three fixes were available: bail on a `TaggedTemplateExpression`, bail on a call
to an i18n-named binding, or drop the `ImportBinding` skip for callables. The
third was rejected on measurement — it would also bail on `z.object({ a:
nonEmptyString() })`, where an imported helper is invoked and the schema hoists
perfectly well. The shipped guard is the first two together, and it costs
exactly 1 finding over the corpus.

### 2. 33.8% false positive against this file's own promise

The bullet above has always said a one-key `z.object({ reason: z.string()
}).parse(body)` inline at its only use is deliberately not flagged, and that
"the default of 1 excludes it". It did not: the gate is `shape.properties.length
< minProperties`, so a default of 1 excludes `z.object({})` and nothing else.
Measured: 219 findings at the old default, **145** at `minProperties: 2` — 74
findings, 33.8%, were the class this document said was already excluded. 54 of
them are zulip, all `z.object({k: …}).parse(response)` inline at the callback
that consumes it; `twenty/…/application-registration-claim.service.ts:342`,
`:376`, `:411` and `zulip/web/src/message_summary.ts:63` were read individually.
The default is now the value the documentation always promised.

### 3. Reporting a fragment of a schema that is itself unhoistable

`astro/packages/astro/src/core/config/schemas/relative.ts:31` reported the
`z.union([z.boolean(), z.literal('jsx')])` under the `compressHTML` key of
`AstroConfigSchema.extend({ … })`, whose SIBLING keys close over the
`fileProtocolRoot` parameter and the `originalBuildClient` local. `isCovered`
only walked to ancestors that are Zod factories in `factories`; `.extend(...)`
and `z.preprocess(...)` are neither, so the fragment was reported on its own.
Prising one key's value out to module scope saves nothing — the object literal
around it is rebuilt per call regardless. Same shape at `:102`, at
`medusa/packages/medusa/src/api/utils/validators.ts:23`
(`originalSchema.extend({ … })` where `originalSchema` is a parameter).

The climb is committed only past a genuine Zod construct. Walking out of a shape
object is provisional until the call wrapping it turns out to be one, because
`tool({ inputSchema: z.object({…}), execute })` also puts a schema in an object
literal — treating that literal as the schema inherits `execute`'s free
variables and suppressed five real findings in
`novu/libs/agent-evals/src/core/tools.ts` in the first draft of this guard.

### A recall bug found while measuring, and fixed

`closesOverNothing` counted a definition as "owned by the enclosing function"
whenever it fell inside that function's source range. A refinement callback's
OWN parameters do — `z.object({…}).refine((options) => …)` declares `options`
inside the schema — so **any schema carrying a `.refine` / `.superRefine` /
`.transform` / `z.preprocess` callback was unreportable**. Definitions inside
the schema's own range now travel with it. Three findings came back, each read
and confirmed true: `astro/packages/integrations/sitemap/src/
validate-options.ts:9`, `medusa/packages/core/utils/src/product/
validators.ts:5`, `medusa/…/common-validators/common.ts:69`. The documented
`documenso` case still bails, because its `superRefine` callback reads a
component PROP, which resolves outside the schema.

### Net

| | findings |
| --- | --- |
| as shipped | 219 |
| `minProperties: 2` | −74 |
| i18n + unhoistable-fragment guards | −4 (all four read, all four false) |
| refinement-callback recall fix | +3 (all three read, all three true) |
| **now** | **145** |
