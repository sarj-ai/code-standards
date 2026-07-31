# `prefer-string-literal-union` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/prefer-string-literal-union.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Flag raw `string` used where a closed enumeration is clearly
intended, and comparison clusters against a fixed set of string literals.
The prescribed replacement is a string-literal union type
(`type Status = "active" | "inactive"`) — NOT a `StrEnum`/`enum`, since the
companion `no-enum` rule bans TypeScript enums.

This is the TypeScript analog of the Python rule SARJ006 (prefer-str-enum).
It fires on two shapes:

1. **Choice-like field** — a `TSPropertySignature` (interface / type literal)
   or class `PropertyDefinition` whose key's last word is one of the
   high-precision CHOICE tokens (`status`, `state`, `kind`, `role`,
   `priority`, `severity`, `direction`, `tier`, `stage`, `type`, `mode`,
   `level`) and whose type annotation is the bare `string` keyword. Because
   open-set API DTO fields (`status: string` from an untyped backend) are the
   dominant false positive, a bare field fires ONLY when CORROBORATED by a
   sibling string-literal-union member in the SAME interface / class / object
   type. A file-wide comparison cluster on the field's name is deliberately
   NOT used to corroborate: it flags unrelated same-named fields (DB-row casts
   like `as Array<{ status: string }>`, passthrough DTOs). The closed-set fact
   is still surfaced — as a `comparisonCluster` diagnostic at the comparison
   site, which is the actionable location.

2. **Comparison cluster** — within one function scope, the same identifier or
   member expression compared (`===` / `!==` / `==` / `!=`, or a `switch`)
   against 2+ distinct short lowercase string literals (each matching
   `^[a-z][a-z0-9_-]{0,30}$`). One diagnostic per cluster. This shape is
   type-aware: it fires ONLY when the compared operand's resolved type is the
   general `string` type. An operand already typed as a string-literal union
   (`CallStatus = "a" | "b"`, a discriminated-union tag) is the target state
   and is suppressed — a syntactic rule can't see through a named/imported
   union, so without type information this shape is inert (the choice-field
   shape still runs).

   A cluster inside the very function that PRODUCES the union is suppressed
   too: when the enclosing function's declared return type is a string-literal
   union containing every compared literal, the `string` parameter is the
   narrowing boundary and MUST stay `string` —
   `function parse(s: string): Status { return s === "a" || s === "b" ? s : null }`
   is the fix, not the violation.

`Literal`-union types (`type X = "a" | "b"`) are the target state and never
fire. Generated files (`*.gen.ts`, `**/generated/**`, `*.d.ts`, or a
`@generated` marker) opt out. Vendor-owned OPEN sets that merely look closed
(a Resend `bounceType`, a Slack `event.subtype` — dozens of values, more added
over time) can be listed in the `ignoreFields` option; narrowing to a union we
don't control would be wrong, not better.
