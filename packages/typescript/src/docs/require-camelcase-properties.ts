/** @fileoverview require-camelcase-properties — the documentation and executable examples of `@sarj/require-camelcase-properties`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_CAMELCASE_PROPERTIES_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Require unquoted lower snake_case TypeScript properties and dot access to use camelCase.",
  rationale: "Unquoted snake_case property syntax makes external wire naming indistinguishable from application-domain naming and lets inconsistent contracts spread through typed code.",
  remediation: "Rename application properties to camelCase. At an external wire boundary, make the exception explicit with a quoted key and bracket access.",
  category: "style",
  autofix: "safe",
  limitations: [
    "Quoted string keys and bracket access are treated as explicit external-wire boundaries.",
    "Computed, numeric, symbol, private, generated, and PascalCase property names are excluded. External-library ownership is not inferred: preserve its spelling using quoted keys and bracket access, or an exact local suppression.",
    "Automatic renaming is limited to an unused private interface or object type alias without heritage, exports, collisions, polymorphic this, computed/indexed keys, merged declarations, or eval. Runtime objects, referenced types and protocol boundaries remain manual.",
  ],
  examples: [
    {
      id: "camelcase-application-shape",
      title: "Use camelCase for an application-facing return shape",
      outcome: "no-match",
      files: [{ path: "src/calls-date-range.ts", source: "export function range(): { dateFrom: string; dateTo: string } { return { dateFrom: '', dateTo: '' }; }" }],
      focusPath: "src/calls-date-range.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "snake-case-application-shape",
      title: "Do not use unquoted wire casing as application property syntax",
      outcome: "match",
      files: [{ path: "src/calls-date-range.ts", source: "export function range(): { date_from: string; date_to: string } { return { dateFrom: '', dateTo: '' }; }" }],
      focusPath: "src/calls-date-range.ts",
      expectedCount: 2,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; interface Local { user_id: string }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; interface Local { userId: string }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
