/** @fileoverview prefer-nullish-filter-predicate — the documentation and executable examples of `@sarj/prefer-nullish-filter-predicate`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION = {
  summary:
    "Prefer an explicit nullish predicate when `filter(Boolean)` removes only nullish values but does not narrow the result type.",
  rationale:
    "An explicit nullish predicate preserves the same runtime elements while letting TypeScript remove `null` and `undefined` from the result.",
  remediation:
    "Replace `filter(Boolean)` with `filter((value) => value !== null && value !== undefined)`.",
  category: "correctness",
  autofix: "safe",
  limitations: [
    "Automatic fixes require a fresh literal array in the source's sole top-level const initializer or expression, with no imports, preceding callouts, or source prototype mutation; other reports retain a suggestion.",
    "Browser HTMLAllCollection/document.all and its structural supertypes are excluded because the browser can expose a falsy object.",
    "The receiver must resolve to the built-in Array or ReadonlyArray filter method.",
    "Broad primitive types, falsy literals, any, unknown, generics, intersections, custom filters, and shadowed Boolean bindings are excluded.",
  ],
  examples: [
    {
      id: "explicit-nullish-predicate",
      title: "Nullish filtering narrows the result",
      outcome: "no-match",
      files: [
        {
          path: "src/users.ts",
          source:
            "declare const users: readonly ({ id: string } | null)[];\nconst present = users.filter((user) => user !== null && user !== undefined);",
        },
      ],
      focusPath: "src/users.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "boolean-nullish-filter",
      title: "Boolean filtering loses nullish narrowing",
      outcome: "match",
      files: [
        {
          path: "src/users.ts",
          source: "declare const users: readonly ({ id: string } | null)[];\nconst present = users.filter(Boolean);",
        },
      ],
      focusPath: "src/users.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "const present = [{ id: 'kept' }, null].filter(Boolean);" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "const present = [{ id: 'kept' }, null].filter((value) => value !== null && value !== undefined);" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
      expectedDiagnostics: [{
        messageId: "preferNullishPredicate",
        message: "This built-in array contains only nullish or provably truthy values, so `filter(Boolean)` preserves runtime values but loses nullish narrowing. Use an explicit nullish predicate.",
        location: { line: 1, column: 47, end: { line: 1, column: 54 } },
        automaticFix: true,
        suggestions: [{
          messageId: "replaceBoolean",
          output: "const present = [{ id: 'kept' }, null].filter((value) => value !== null && value !== undefined);",
        }],
      }],
    },
    {
      id: "nonfresh-suggestion-only",
      title: "Suggest a nullish predicate without assuming a fresh receiver",
      outcome: "match",
      files: [{ path: "src/users.ts", source: "declare const users: readonly ({ id: string } | null)[];\nconst present = users.filter(Boolean);" }],
      focusPath: "src/users.ts",
      expectedCount: 1,
      expectedDiagnostics: [{
        messageId: "preferNullishPredicate",
        message: "This built-in array contains only nullish or provably truthy values, so `filter(Boolean)` preserves runtime values but loses nullish narrowing. Use an explicit nullish predicate.",
        location: { line: 2, column: 30, end: { line: 2, column: 37 } },
        automaticFix: false,
        suggestions: [{
          messageId: "replaceBoolean",
          output: "declare const users: readonly ({ id: string } | null)[];\nconst present = users.filter((value) => value !== null && value !== undefined);",
        }],
      }],
    },
  ],
} as const satisfies RuleDocumentation;
