# `zod-naming-convention` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/zod-naming-convention.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Enforce a consistent naming convention for Zod schemas, so a
schema is recognisable at its use site without chasing the declaration.

BOTH conventions are accepted by default (`convention: "either"`):
  - `Z`-prefix (`ZUser = z.object({...})`) — lets a schema and its inferred
    type share a base name (`type User = z.infer<typeof ZUser>`).
  - `Schema`-suffix (`userSchema`, `SubmitFormDataSchema`) — the dominant
    convention in the wider Zod ecosystem and in most existing codebases.

Defaulting to prefix-only was wrong on both counts. It contradicted the rest
of the plugin — `require-zod-form-validation` accepts `/Schema$|^Z[A-Z]/` as
"this is a Zod schema" — and on a real 42k-LOC codebase that uniformly uses
the suffix it declared 220 symbols non-conforming with no defect behind any of
them. Both regexes now come from `_zod.ts` so the two rules cannot drift
apart again.

A team that wants exactly one form sets `convention: "prefix"` or
`convention: "suffix"`; the point of the rule is consistency, and either
choice delivers it.

FALSE POSITIVES FOUND BY A 2220-FILE CORPUS SWEEP (zod / TanStack Query /
react-router / swr / zustand, 2026-07). The rule fired 1816 times, ALL of
them in the `zod` repo and none of them a defect. Three guards remove them:

  (a) TEST FILES — 1783 / 1816 hits. A schema declared inside a test is a
      throwaway fixture named `a`, `b`, `t1`, read three lines below its
      declaration; there is no cross-module use site for the convention to
      serve. `zod/packages/zod/src/v4/classic/tests/index.test.ts:782`
      (`const a = z.lazy(() => z.string())`) is representative — that file
      alone contributed 70 reports.
  (b) TERMINAL CALLS THAT DO NOT RETURN A SCHEMA — ~280 hits. The rule keyed
      off "the callee chain starts at `z`", which is also true of
      `z.string().safeParse(x)` (a RESULT), `z.toJSONSchema(s)` (a plain JSON
      object), `z.registry()` (a registry), `codec.encode(v)` / `.decode(v)`
      (a converted VALUE) and `z.function(...).implement(fn)` (a function).
      Demanding a `Schema` suffix on any of those is simply wrong.
      `zod/packages/zod/src/v3/tests/record.test.ts:166`
      (`const result1 = z.record(z.any()).parse({ foo: undefined })`).
  (c) NAMES THAT ALREADY SAY "SCHEMA" — 421 hits. `ZOD_SUFFIX_RE` is anchored
      AND case-sensitive, so `schema`, `schema1` and `numberSchemaOptional`
      were all declared non-conforming despite being unmistakable at a
      glance. `schema` alone accounts for 371 reports, e.g.
      `zod/packages/treeshake/zod-string.ts:3`. This widens only the ACCEPT
      side, so it cannot make `require-zod-form-validation` — which uses the
      shared `_zod.ts` recognisers to accept a receiver — reject anything it
      previously accepted.

SECOND SWEEP (25,508 deduped TS/TSX files across zod / trpc / dub /
openstatus / formbricks / documenso / unkey / midday / papermark / cal.com /
hono plus six first-party repos, 2026-07): 536 hits, 39 read in a seeded
random sample — 6 true positives, 2 false positives, 31 arguable. At a 5%
false-positive rate the rule is clean, and one guard (d) closes the only
class found: BENCHMARK FIXTURES, 12 / 536, 10 of them in zod's own repo.
`zod/packages/zod/src/v3/benchmarks/object.ts:9-10` declares `empty` / `short`
/ `long` and feeds each to a suite three lines below — verbatim the rationale
for guard (a), on a path the test predicate simply does not reach.

REFUTED, and worth recording so it is not re-derived: this is NOT the rule
flagging zod's own library source. Only 16 of the 536 findings are in the zod
repo and 10 of those are benchmarks; 489 / 536 (91%) are in four zod
CONSUMERS.

NOT A DEFECT, NOT A FALSE POSITIVE: 325 of 536 (60.6%) of the names end in
Input / Output / Response / Request / Payload / Params / Shape / Result /
Enum / Config / Query — a third, internally consistent convention, several of
them deliberately declaration-merged with the inferred type of the same name,
which achieves exactly what the `Z` prefix exists for. Those are arguable, not
wrong. If that population is worth accommodating, the shape to add is an
`extraPatterns: string[]` option (or a fourth built-in `"role-suffix"`
convention) that is STRICT OPT-IN and changes nothing by default — a rule
whose accept side widens by default stops being a consistency rule. It is
deliberately not implemented here: no measurement in this sweep showed a
defect behind those names, so there is nothing yet to justify the surface.
