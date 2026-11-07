/** @fileoverview stepdown — the documentation and executable examples of `@sarj/stepdown`. */

import type { RuleDocumentation } from "../documentation.js";

export const STEPDOWN_DOCUMENTATION = {
  summary: "Place a private helper below its sole direct same-scope caller.",
  rationale:
    "Caller-first ordering lets a reader follow the main flow before descending into implementation details.",
  remediation:
    "Consider moving the private helper below its sole caller after reviewing initialization and reflection dependencies.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Generated and test files, cycles, dynamic or escaped references, overload targets, and helpers with multiple callers are excluded; immutable local callable aliases are followed only when every use stays in the caller. Function bodies include nested sibling helpers.",
    "Class helpers must be private; their sole caller may be public, protected, or private by default. Set privateBandOnly alongside accessibility ordering to restrict class reports to private callers; module and nested function ordering is unchanged.",
    "Runtime class-field, static-block, computed-member, and decorator barriers are never crossed; non-hoisted module helpers also cannot cross eager execution or unrelated initialization.",
    "Automatic ordering only applies to an explicit module containing ordinary named function declarations, exactly one exported entry and a reachable acyclic single-caller helper tree, with no comments, eval, overloads, generics or eager statements. Class methods, variables and other module layouts remain manual because reflection, initialization and module cycles can matter.",
  ],
  examples: [
    {
      id: "caller-before-helper",
      title: "Place the caller first",
      outcome: "no-match",
      files: [
        {
          path: "src/run.ts",
          source:
            "function run() { return load(); }\nfunction load() { return 1; }",
        },
      ],
      focusPath: "src/run.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "helper-before-caller",
      title: "Do not lead with a sole-caller helper",
      outcome: "match",
      files: [
        {
          path: "src/run.ts",
          source:
            "function load() { return 1; }\nfunction run() { return load(); }",
        },
      ],
      focusPath: "src/run.ts",
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
            "function load() { return 1; }\nexport function run() { return load(); }",
        },
      ],
      fixedFiles: [
        {
          path: "src/autofix-example.ts",
          source:
            "export function run() { return load(); }\nfunction load() { return 1; }",
        },
      ],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
