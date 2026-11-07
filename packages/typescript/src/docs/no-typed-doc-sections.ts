/** @fileoverview no-typed-doc-sections — the documentation and executable examples of `@sarj/no-typed-doc-sections`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_TYPED_DOC_SECTIONS_DOCUMENTATION = {
  summary: "Reject typed-signature repetition while preserving behavior that types cannot express.",
  rationale:
    "Parameter and return tags repeat typed signatures and can drift without adding runtime behavior or constraints.",
  remediation: "Remove repeated parameter and return tags; retain documentation for behavior, failures, and external contracts.",
  category: "maintainability",
  autofix: "safe",
  limitations: ["Description-free or name-restating tags require the adjacent explicitly typed signature and a corresponding parameter name. Optional/defaulted or nested parameter tags and unproven explicit JSDoc types are preserved."],
  examples: [
    {
      id: "behavioral-documentation",
      title: "Keep behavior that the signature cannot express",
      outcome: "no-match",
      files: [{ path: "src/client.ts", source: "/** Retries when the vendor returns 429. */\nexport function fetchValue(id: string): number { return 1; }" }],
      focusPath: "src/client.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "restated-parameter",
      title: "Do not expand a typed parameter's name",
      outcome: "match",
      files: [{ path: "src/client.ts", source: "/** @param userId the user identifier */\nexport function fetchValue(userId: string): number { return 1; }" }],
      focusPath: "src/client.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "/** @param id the identifier */\nfunction read(id: string): string { return id; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "\nfunction read(id: string): string { return id; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
