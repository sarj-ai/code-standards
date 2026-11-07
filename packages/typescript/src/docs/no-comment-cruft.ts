/** @fileoverview no-comment-cruft — the documentation and executable examples of `@sarj/no-comment-cruft`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_COMMENT_CRUFT_DOCUMENTATION = {
  summary: "Flag commented-out code, section-banner comments, and leading file-header comment preambles.",
  rationale:
    "Decorative, narrated, or dead-code comments obscure the constraints and rationale that comments should preserve.",
  remediation:
    "Delete dead code and narration; express boundaries with named code and retain only comments that explain constraints or intent.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "The rule skips generated files and conservatively preserves prose, issue references, licenses, examples, and tool directives. Automatic fixes remove only whole-line punctuation-only banners while preserving line endings; narrated prose, unfinished work and contextual labels remain manual.",
  ],
  examples: [
    {
      id: "owned-context",
      title: "A reference records why the counter changes",
      outcome: "no-match",
      files: [{ path: "src/counter.ts", source: "// increment the counter for PLT-812\ncounter += 1;" }],
      focusPath: "src/counter.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "redundant-narration",
      title: "A comment repeats the statement below",
      outcome: "match",
      files: [{ path: "src/counter.ts", source: "// increment the counter\ncounter += 1;" }],
      focusPath: "src/counter.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "const first = 1;\n// =================\nconst second = 2;" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "const first = 1;\n\nconst second = 2;" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
