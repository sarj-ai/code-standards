/** @fileoverview no-conditional-empty-object-spread — the documentation and executable examples of `@sarj/no-conditional-empty-object-spread`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_CONDITIONAL_EMPTY_OBJECT_SPREAD_DOCUMENTATION = {
  summary:
    "Build conditional properties explicitly instead of spreading an empty-object branch.",
  rationale:
    "An empty-object conditional spread hides whether a property is omitted, which differs from assigning undefined.",
  remediation:
    "Construct the object explicitly and add the conditional fields only when the original condition holds, preserving evaluation order and ownership.",
  category: "style",
  autofix: "safe",
  limitations: [
    "Reports ternary expressions with an empty object branch directly spread into an object literal. Does not report array or argument spreads, logical spreads, or two nonempty alternatives.",
    "This is an explicit readability policy. Comment-free conditionals with exactly one nonempty object-literal branch are automatically rewritten as logical spreads, preserving omission, evaluation order and property ownership. Other expression branches require manual review.",
  ],
  examples: [
    {
      id: "before",
      title: "Preserve the explicit contract",
      outcome: "match",
      files: [
        {
          path: "src/example.ts",
          source:
            "declare const includePage: boolean;\nconst query = { limit: 20, ...(includePage ? { page: 1 } : {}) };",
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "after",
      title: "Use the direct contract",
      outcome: "no-match",
      files: [
        {
          path: "src/example.ts",
          source:
            "declare const includePage: boolean;\nconst query: { limit: number; page?: number } = { limit: 20 };\nif (includePage) query.page = 1;",
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "declare const enabled: boolean; const value = { ...(enabled ? { item: 1 } : {}) };" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "declare const enabled: boolean; const value = { ...(!!(enabled) && ({ item: 1 })) };" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
