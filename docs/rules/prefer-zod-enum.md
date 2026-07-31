# `prefer-zod-enum` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/prefer-zod-enum.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Prefer `z.enum(["a", "b"])` over a union of Zod string
literals. The enum form is shorter, exposes the permitted values directly,
and infers the same string-literal union.

The fix is deliberately limited to direct, non-empty arrays containing only
`z.literal(<string>)` calls. Spreads, identifiers, non-string literals, and
commented arrays are reported without an automatic rewrite because moving or
discarding their syntax would not be mechanical.
