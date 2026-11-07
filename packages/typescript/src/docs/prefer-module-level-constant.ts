/** @fileoverview prefer-module-level-constant — the documentation and executable examples of `@sarj/prefer-module-level-constant`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_MODULE_LEVEL_CONSTANT_DOCUMENTATION = {
  summary:
    "Hoist literal-only constant collections and regexes out of function bodies to module scope so they are allocated once.",
  rationale:
    "Recreating immutable lookup data on every call wastes allocations and obscures its constant nature.",
  remediation:
    "Declare immutable literal collections and non-stateful regular expressions once at module scope.",
  category: "performance",
  autofix: "safe",
  limitations: [
    "Automatic fixes only hoist an existing readonly literal-string array from a sole exported ordinary function that only returns its native includes lookup on a string parameter. No imports, other declarations, comments, identity escapes or source prototype mutations are permitted.",
    "Small collections, observed direct or nested mutations, nested aliases, direct escapes, and dependencies on local values are excluded. Directly invoked function expressions are excluded rather than assuming they run repeatedly. Callback effects and indirect escapes are not analyzed interprocedurally; review those before hoisting.",
    "Builtin constructor and non-retaining call assumptions require unshadowed identifiers; local declarations conservatively abstain. Runtime replacement of globals is not modeled.",
  ],
  examples: [
    {
      id: "hoisted-collection",
      title: "Hoist a constant collection",
      outcome: "no-match",
      files: [
        {
          path: "src/keys.ts",
          source:
            "const KEYS = ['a', 'b', 'c'] as const; function isAllowed(key: string) { return KEYS.includes(key); }",
        },
      ],
      focusPath: "src/keys.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "local-collection",
      title: "Do not recreate a constant collection",
      outcome: "match",
      files: [
        {
          path: "src/keys.ts",
          source:
            "function isAllowed(key: string) { const KEYS = ['a', 'b', 'c']; return KEYS.includes(key); }",
        },
      ],
      focusPath: "src/keys.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven source-owned correction",
      outcome: "match",
      files: [
        {
          path: "src/autofix-example.ts",
          source:
            "export function isAllowed(key: string) { const KEYS: readonly string[] = ['a', 'b', 'c']; return KEYS.includes(key); }",
        },
      ],
      fixedFiles: [
        {
          path: "src/autofix-example.ts",
          source:
            "const KEYS: readonly string[] = ['a', 'b', 'c'];\nexport function isAllowed(key: string) { return KEYS.includes(key); }",
        },
      ],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
