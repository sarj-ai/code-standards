# `prefer-discriminated-union` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/prefer-discriminated-union.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Flag object types that model mutually-exclusive states with a
boolean status flag plus many optional members. A shape like
`{ success: boolean; data?: T; error?: E; code?: number }` encodes "success
vs. error" implicitly and lets illegal states (e.g. `success: true` with an
`error`) be representable.

Such shapes should be modelled as a discriminated union, e.g.
`{ ok: true; data: T } | { ok: false; error: E }`, so the compiler enforces
that exactly one branch's fields are present.

This is the TypeScript mirror of the Python rule SARJ005.

A PAYLOAD IS REQUIRED. The defect is that a payload can be present in the
wrong branch (`success: true` carrying an `error`), so the shape must have at
least one optional member that is NOT itself a boolean. An all-boolean record
is a FLAG SET, not a state machine: every combination of its members is legal,
so there is no illegal state to make unrepresentable and a discriminated union
would be strictly worse.

Corpus evidence (2220 files across zod / TanStack Query / react-router / swr /
zustand, 2026-07): the rule fired exactly once, and it was this false
positive — `swr/src/_internal/types.ts:1191`,
`interface StateDependencies { data?: boolean; error?: boolean;
isValidating?: boolean; isLoading?: boolean }`. That is SWR's dependency
TRACKER: each flag records "did the render read this field?", and all sixteen
combinations are meaningful.
