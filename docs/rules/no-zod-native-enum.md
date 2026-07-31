# `no-zod-native-enum` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-zod-native-enum.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Disallow `z.nativeEnum(...)` in zod schemas; use
`z.enum(["a", "b"])` and derive the type with `z.infer<typeof Schema>`.

Rationale — this is the schema-layer sibling of the `no-enum` rule. Zod's
`nativeEnum` exists for exactly one purpose: to wrap a TypeScript `enum`,
which `no-enum` already bans (enums emit runtime code, have unintuitive
numeric defaults, and don't tree-shake). Reaching for `nativeEnum` is
therefore either (a) importing a banned construct through the back door, or
(b) wrapping an `as const` object, in which case `z.enum` over the value list
is the shorter, better-inferring form. Either way the target state is the
same string-literal union `no-enum` prescribes, so the two rules point at one
destination.

Two shapes fire:

1. **`z.nativeEnum(x)`** — always. Autofixable ONLY when the argument is an
   inline object literal (optionally `as const`) whose every value is a
   string literal: that set is fully known at the call site, so the rewrite
   to `z.enum([...])` is mechanical and value-preserving. A numeric member
   (`{ A: 1 }`) is NOT fixed — `z.enum` accepts strings only, so rewriting
   would silently change the accepted input. A spread, computed key, shorthand
   property, method, or an empty object is not fixed either (the member set
   isn't statically known, and `z.enum([])` is not a valid schema). An
   identifier argument (`z.nativeEnum(Fruits)`) is reported without a fix:
   inlining the values at the call site would duplicate the literal set that
   the named object exists to own, so the correct edit is a human one.

2. **`z.enum(SomeTsEnum)`** — zod v4 lets `z.enum` take a TS enum directly,
   which is `nativeEnum` under a friendlier name and re-opens the same hole.
   Detected two ways: lexical resolution of the identifier to a
   `TSEnumDeclaration` in the same file, and — when type information is
   available — the resolved symbol carrying an enum flag, which also catches
   an enum imported from another module. `z.enum(COLORS)` where `COLORS` is a
   `readonly string[]` / `as const` array is the prescribed pattern and never
   fires.

False positives handled: a bare `nativeEnum(...)` call fires only when the
name is imported from a zod module, so a same-named local helper is not
flagged. Generated files (`*.gen.ts`, `**/generated/**`, `*.d.ts`, or a
`@generated` marker) opt out, matching `no-enum` — codegen from an OpenAPI
spec legitimately emits enums and the schemas that wrap them.

TEST FILES ARE EXEMPT. Corpus sweep (2220 files across zod / TanStack Query /
react-router / swr / zustand, 2026-07): 32 raw hits, 32 of them in test files
and 100% false positives. A test that covers `z.nativeEnum` has to CALL
`z.nativeEnum` — `zod/packages/zod/src/v3/tests/nativeEnum.test.ts:12`
(`const fruitEnum = z.nativeEnum(Fruits)`) is not importing a banned construct
through the back door, it is the coverage for the construct. The same applies
to any consumer pinning the migration behaviour of a legacy enum schema, and
it mirrors the exemption `no-enum` already grants generated code: the rule
targets the DECISION to model a domain with an enum, and a fixture makes no
such decision.

## Provenance

Mined from two years of PR review (SARJ-928). Schema-layer sibling of `no-enum`;
autofixable for an inline string-literal object.
