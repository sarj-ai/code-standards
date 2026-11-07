/** @fileoverview no-trailing-value-narration — the documentation and executable examples of `@sarj/no-trailing-value-narration`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_TRAILING_VALUE_NARRATION_DOCUMENTATION = {
  summary: "Flag a trailing comment that repeats the line's numeric value only to name its unit.",
  rationale: "A repeated value can disagree with the expression after either the code or comment changes.",
  remediation: "Put the unit in the identifier and keep comments only when they explain a constraint or non-obvious conversion.",
  category: "maintainability",
  autofix: "safe",
  aliases: ["trailing-value-narration"],
  limitations: ["Only attached declaration, property, or assignment values containing numeric tokens and comments with recognized unit words are inspected. Deletion requires a numeric literal and the same unit on its owner. Constraints, additional prose, unknown expressions on unit-bearing owners, and cross-unit annotations are preserved; conversions are not evaluated."],
  examples: [
    {
      id: "explain-constraint",
      title: "Explain a domain constraint",
      outcome: "no-match",
      files: [{ path: "src/timeouts.ts", source: "const timeout = 5 * 60; // 5 minutes for cold starts" }],
      focusPath: "src/timeouts.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "repeat-duration",
      title: "Do not narrate the numeric duration",
      outcome: "match",
      files: [{ path: "src/timeouts.ts", source: "const staleTime = 5 * 60 * 1000; // 5 minutes" }],
      focusPath: "src/timeouts.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "const POLL_MS = 3; // 3 ms" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "const POLL_MS = 3;" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
