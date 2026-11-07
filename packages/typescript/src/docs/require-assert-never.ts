/** @fileoverview require-assert-never — the documentation and executable examples of `@sarj/require-assert-never`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_ASSERT_NEVER_DOCUMENTATION = {
  summary:
    "Require an empty switch default to call `assertNever` so discriminated unions remain exhaustive at compile time.",
  rationale:
    "An empty default silently accepts new union members instead of making the compiler identify the missing case.",
  remediation:
    "Call `assertNever` with the discriminant in the exhaustive switch default.",
  category: "correctness",
  autofix: "safe",
  limitations: [
    "Requires type information and singleton case values covering the current union. The helper must accept never to provide a compile-time check; its spelling alone is not a proof of that contract. Review the desired runtime behavior for unexpected external values.",
    "Automatic fixes reuse only an existing private ordinary assertNever function with one never parameter, explicit void return and an exactly empty body. The complete comment-free module must otherwise contain only one exported ordinary function with an explicit primitive return type, one string-literal-union parameter, a complete switch with primitive literal returns and a final empty or break default, followed by a primitive fallback return. The existing helper is called in that default, preserving unexpected-value continuation while adding the never compile guard. Throwing helpers, other statements or exports, imports, defaults, aliases and dynamic behavior remain manual.",
  ],
  examples: [
    {
      id: "assert-never-default",
      title: "Make the default exhaustive",
      outcome: "no-match",
      files: [
        {
          path: "src/render.ts",
          source:
            "function assertNever(value: never): never { throw new Error(`Unexpected kind: ${String(value)}`); }\ndeclare const kind: 'a' | 'b';\nswitch (kind) { case 'a': break; case 'b': break; default: assertNever(kind); }",
        },
      ],
      focusPath: "src/render.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "empty-default",
      title: "Do not leave an exhaustive default empty",
      outcome: "match",
      files: [
        {
          path: "src/render.ts",
          source:
            "declare const kind: 'a' | 'b';\nswitch (kind) { case 'a': break; case 'b': break; default: }",
        },
      ],
      focusPath: "src/render.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Reuse the existing no-op never guard",
      outcome: "match",
      files: [
        {
          path: "src/render.ts",
          source:
            "function assertNever(_value: never): void {}\nexport function render(kind: 'a' | 'b'): number { switch (kind) { case 'a': return 1; case 'b': return 2; default: break; } return 0; }",
        },
      ],
      fixedFiles: [
        {
          path: "src/render.ts",
          source:
            "function assertNever(_value: never): void {}\nexport function render(kind: 'a' | 'b'): number { switch (kind) { case 'a': return 1; case 'b': return 2; default: assertNever(kind); break; } return 0; }",
        },
      ],
      focusPath: "src/render.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
