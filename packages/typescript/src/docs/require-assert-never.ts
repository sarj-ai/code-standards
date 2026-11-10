/** @fileoverview require-assert-never — the documentation and executable examples of `@sarj/require-assert-never`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_ASSERT_NEVER_DOCUMENTATION = {
  summary:
    "Require a never witness in empty switch defaults so discriminated unions remain exhaustive at compile time.",
  rationale:
    "An empty default silently accepts new union members instead of making the compiler identify the missing case.",
  remediation:
    "Use `void (value satisfies never)` or a helper accepting never, preserving the intended runtime fallback.",
  category: "correctness",
  autofix: "safe",
  limitations: [
    "Requires type information and singleton case values covering the current union. The helper must accept never to provide a compile-time check; its spelling alone is not a proof of that contract. Review the desired runtime behavior for unexpected external values.",
    "Unique-symbol alternatives are compared by native compiler type identity. Distinct symbols can share the same printed type name; a handled symbol or its typed alias covers only that identity. Unavailable literal names do not establish coverage.",
    "Automatic fixes add void (parameter satisfies never), which only reads the existing parameter at runtime and introduces no helper dependency when the exported function is serialized on its own. The complete comment-free module must contain one exported ordinary function, optionally preceded by an exactly empty private ordinary assertNever helper with one never parameter and explicit void return. The dispatcher needs one string-literal-union parameter, an explicit primitive return type, a complete switch with primitive literal returns and a final empty or break default, followed by a primitive fallback return. Other module statements, imports, defaults, aliases, async functions and dynamic behavior remain manual.",
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
      title: "Keep the never witness local to the dispatcher",
      outcome: "match",
      files: [
        {
          path: "src/render.ts",
          source:
            "export function render(kind: 'a' | 'b'): number { switch (kind) { case 'a': return 1; case 'b': return 2; default: break; } return 0; }",
        },
      ],
      fixedFiles: [
        {
          path: "src/render.ts",
          source:
            "export function render(kind: 'a' | 'b'): number { switch (kind) { case 'a': return 1; case 'b': return 2; default: void (kind satisfies never); break; } return 0; }",
        },
      ],
      focusPath: "src/render.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
