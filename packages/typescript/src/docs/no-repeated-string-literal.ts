/** @fileoverview no-repeated-string-literal — the documentation and executable examples of `@sarj/no-repeated-string-literal`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_REPEATED_STRING_LITERAL_DOCUMENTATION = {
  summary:
    "Disallow a long structured string literal repeated across functions; the copies drift when one is edited. Extract a module-level constant.",
  rationale:
    "Independent copies of a query, route template, or identifier can diverge and silently change behavior.",
  remediation:
    "Extract the repeated value to one module-level constant and reference it from each function.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Test files, short strings, prose, substitutions, module sources, JSX attributes, and repetition within one function are excluded.",
    "Automatic edits only reuse an already authored and already read private const primitive string declared first in an otherwise declaration-only explicit module. All ordinary zero-argument functions must directly return that constant or the identical literal. Imports, comments, annotations on the constant, other statements or uses, callbacks, shadowing, generics and initialization effects remain manual; no domain name is invented.",
  ],
  examples: [
    {
      id: "shared-constant",
      title: "Share one structured value",
      outcome: "no-match",
      files: [
        {
          path: "src/queries.ts",
          source:
            "const QUERY = 'SELECT id, status, created_at FROM candidates';\nfunction one() { return QUERY; }\nfunction two() { return QUERY; }",
        },
      ],
      focusPath: "src/queries.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "repeated-query",
      title: "Do not copy a structured value across functions",
      outcome: "match",
      files: [
        {
          path: "src/queries.ts",
          source:
            "function one() { return 'SELECT id, status, created_at FROM candidates'; }\nfunction two() { return 'SELECT id, status, created_at FROM candidates'; }",
        },
      ],
      focusPath: "src/queries.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Reuse the existing primitive constant",
      outcome: "match",
      files: [
        {
          path: "src/queries.ts",
          source:
            "const QUERY = 'SELECT id, status, created_at FROM candidates';\nexport function current() { return QUERY; }\nexport function one() { return 'SELECT id, status, created_at FROM candidates'; }\nexport function two() { return 'SELECT id, status, created_at FROM candidates'; }",
        },
      ],
      fixedFiles: [
        {
          path: "src/queries.ts",
          source:
            "const QUERY = 'SELECT id, status, created_at FROM candidates';\nexport function current() { return QUERY; }\nexport function one() { return QUERY; }\nexport function two() { return QUERY; }",
        },
      ],
      focusPath: "src/queries.ts",
      expectedCount: 2,
    },
  ],
} as const satisfies RuleDocumentation;
