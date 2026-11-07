/** @fileoverview test-phase-label-comment — the documentation and executable examples of `@sarj/test-phase-label-comment`. */

import type { RuleDocumentation } from "../documentation.js";

export const TEST_PHASE_LABEL_COMMENT_DOCUMENTATION = {
  summary: "Tests must not use bare Arrange, Act, Assert, Given, When, or Then phase comments.",
  rationale: "Phase labels narrate test structure without explaining behavior and often hide unclear names or oversized tests.",
  remediation: "Delete the label; if the phases remain hard to follow, extract a named helper or split the test.",
  category: "testing",
  autofix: "safe",
  limitations: [
    "Only standalone line comments in recognized test files are checked.",
    "Comments inside bracketed expressions or containing words outside the bounded phase grammar are preserved.",
  ],
  examples: [
    {
      id: "behavioral-comment",
      title: "Behavioral consequence is retained",
      outcome: "no-match",
      files: [{ path: "widget.test.ts", source: "// Then the retry loop would spin forever.\nexpect(run()).toBe(true);" }],
      focusPath: "widget.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "bare-phase-label",
      title: "Bare phase label is removed",
      outcome: "match",
      files: [{ path: "widget.test.ts", source: "const seed = 1;\n// Arrange\nconst widget = makeWidget();" }],
      focusPath: "widget.test.ts",
      expectedCount: 1,
      fixedFiles: [{ path: "widget.test.ts", source: "const seed = 1;\n\nconst widget = makeWidget();" }],
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
