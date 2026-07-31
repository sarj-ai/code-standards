# `prefer-zod-infer` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/prefer-zod-infer.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Flag a hand-written `interface`/`type` that restates the shape
of a Zod schema declared in the same module. The type must be DERIVED:

  const UserSchema = z.object({ id: z.string(), name: z.string() });
  interface User { id: string; name: string }   // twin — drifts silently
  type User = z.infer<typeof UserSchema>;       // derived — cannot drift

The defect is silent: a field added to the schema and not to the twin fails
nothing at build time. The parsed value simply carries a member the type says
does not exist, and every read of it is a `never`-narrowed branch or a cast.

MEASUREMENT (2026-07). The rule as shipped was run over 30,759 `.ts`/`.tsx`
files in seventeen repositories — seven maintained internally plus zod, trpc,
dub, openstatus, formbricks, documenso, unkey, midday, papermark and cal.com.
3,622 of those files import Zod and hold 7,255 schemas, 3,432 `z.infer`
aliases (the convention is already the norm; this rule is the ratchet) and
1,657 hand-written object types.

IT REPORTS 5 TIMES, and all five are true positives, every one of them in a
public repository:

  midday/packages/categories/src/types.ts:4       BaseCategory
  midday/packages/accounting/src/types.ts:256     BaseProviderConfig
  openstatus/packages/status-fetcher/src/types.ts:59  ApiConfig
  openstatus/packages/status-fetcher/src/types.ts:65  StatusPageEntry
  documenso/packages/lib/jobs/client/_internal/job.ts:5  SimpleTriggerJobOptions

Each is a member-for-member restatement of a schema declared in the same
file — `interface BaseProviderConfig` sits directly under
`BaseProviderConfigSchema` with the doc comments copied across, and
openstatus's file introduces its pair under the comment "Interfaces using
derived types", which is exactly what they are not. Zero reports in the seven
internal repos: the pairs that exist there are all deliberate (see (d), (f)).

WHAT EACH GUARD REMOVES, measured by disabling it and re-running the sweep:

  (a) tests + generated files   +2   both in zod's own `object.test.ts`
  (f) `.transform()` sibling    +2   both in one internal module
  (b) generic type parameters   +0   (+1 at the looser tier below)
  (c) `z.ZodType<T>` arguments  +0   (see below — kept anyway)

WHY NAME CORRELATION IS REQUIRED. The obvious alternative — flag any type
whose key set equals some schema's in the file, names ignored — was measured
on the same corpus with every other guard in place: 13 reports, 4 true
positives and 9 false. The 9 share one shape: a DB-row or wire-input type
that happens to share a key set with the response schema it is mapped into
(`{ id, name, roles }` on both sides of a mapping function, the nested member
types entirely different). Key-set coincidence is cheap at three or four
members; a matching NAME is what makes the pair a claim about the same thing.

`requireIdenticalShape: false` drops the member-by-member comparison and
reports on name correlation alone: 8 hits on the same corpus, the 5 above
plus openstatus's `Monitor` (a five-member type against a three-key schema —
the one false positive), midday's `TaxRateConfig` (a twin that has ALREADY
drifted: the interface admits `null` where the schema's `z.enum` does not)
and cal.com's `CalendarState` (a real twin whose one `.transform()`ed member
the strict tier cannot verify). It is the right setting for a repo that wants
the drift caught rather than only the exact duplicates, at ~1 in 8 noise.

GUARDS, each earned by a measured false positive:

  (a) TESTS AND GENERATED FILES. 152 of the 171 name-correlated pairs in the
      corpus are in `*.test.ts` or generated output. A schema and a type
      declared side by side in a parser test are the two halves of the
      assertion, not a duplication — `zod/packages/zod/src/v4/classic/tests/
      object.test.ts:13` declares `type TestType` beside `const Test`.
  (b) GENERIC TYPES. `z.infer` cannot produce a type parameterised by the
      caller, so a generic twin is not a twin.
      `documenso/packages/lib/types/search-params.ts:50` declares
      `export type FindResultResponse<T>` over the keys of
      `ZFindResultResponse`, and the line above it reads "// Can't infer
      generics from Zod."
  (c) `z.ZodType<T>` ANNOTATIONS — the SUPPORTED direction for constraining a
      schema to an existing type. 446 annotation sites in the corpus (314 in
      unkey, 61 in cal.com); flagging `T` would tell an author to invert a
      dependency the language cannot invert. It removes nothing measurable
      today ONLY because cal.com, which uses the pattern at scale, prefixes
      the hand-written type with `T` (`TCreateInputSchema` beside
      `ZCreateInputSchema`) so the names never correlate. The moment a repo
      writes the ordinary `interface ApiKey` / `const apiKeySchema:
      z.ZodType<ApiKey>`, this guard is the only thing standing between the
      rule and backwards advice — hence it ships with a test rather than
      waiting for the report. ALL type arguments are collected, not just the
      first: cal.com's tRPC inputs use `z.ZodType<Output, Def, Input>`, and
      reading only the first names the wrong type
      (`packages/trpc/server/routers/viewer/bookings/get.schema.ts:29`).
  (d) SCHEMAS THAT ARE NOT PLAIN OBJECT LITERALS. `z.looseObject`,
      `.partial()`, `.passthrough()`, `.catchall()`, `.omit()`, `.merge()`
      and friends all mean the inferred type is deliberately not the shape
      written at the call site. The two internal pairs this removes are both
      `z.looseObject` LENIENT wire schemas (`.nullish()` on every field)
      beside the STRICT domain type a hand-written parse function returns —
      parse-don't-validate, working as intended.
  (e) PER-KEY OPTIONALITY AND TYPE DISAGREEMENT. A twin restates the shape;
      anything that disagrees is a deliberately different type. This is what
      removes the snake_case-wire vs camelCase-domain pairs — a shared base
      name, a shared member count, and almost no shared members.
  (f) SCHEMAS FED THROUGH `.transform()` ELSEWHERE IN THE MODULE. When a
      module declares `const XCamel = XSchema.transform(...)`, a hand-written
      `X` plausibly describes the POST-transform value, and `z.infer<typeof
      XSchema>` — what this rule would otherwise point at — is the wrong
      answer. Two internal reports, both in one module whose eight interfaces
      are the camelCase outputs of eight snake_case schemas.
  (g) INTERFACES WITH `extends`, and aliases that are not a bare object
      literal: a type that adds to or narrows a schema's shape is not
      restating it.

ONE MEMBER MUST POSITIVELY AGREE. A pair whose members are all references to
other symbols (`role: Role` against `role: RoleSchema`) proves nothing about
the two being the same shape, so the rule needs at least one member whose Zod
leaf and TypeScript annotation demonstrably match before it reports.

THE COST is recall, deliberately. cal.com's `CalendarState` is a genuine twin
that the strict tier stays quiet about because one member is
`z.string().optional().transform(...)`, and a hand-written type whose name
does not correlate with its schema (`FormValues` beside `formSchema`) is
never reached at all. Both are visible at `requireIdenticalShape: false`.

THE INVERSE SMELL is real and NOT covered here: `const XSchema:
z.ZodType<HandWrittenX> = z.object({...})` forces the schema to satisfy a
hand-written type, which type-checks the schema against the type but leaves
the type hand-maintained — inference flowing the wrong way. It is legitimate
in generic library code (`schema?: z.ZodType<Schema>` as a parameter bound)
and a smell only when the argument is a concrete local type, so separating
the two needs its own measurement pass and its own rule.
