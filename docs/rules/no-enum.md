# `no-enum` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-enum.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Disallow TypeScript `enum` declarations. Use string-literal
union types (e.g. `type Status = "active" | "inactive"`) or `as const`
objects instead — enums generate runtime code, have unintuitive numeric
defaults, and don't tree-shake cleanly.

Generated files can opt out either by living under a path matched by
`ignoreFiles` (default: `**/generated/**`, `**/*.gen.ts`, `**/*.generated.ts`)
or by including a `@generated` marker comment near the top of the file.
