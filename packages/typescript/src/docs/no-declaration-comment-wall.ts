/** @fileoverview no-declaration-comment-wall — the documentation and executable examples of `@sarj/no-declaration-comment-wall`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_DECLARATION_COMMENT_WALL_DOCUMENTATION = {
  summary: "Flag an enum body or class body whose member comments mostly re-spell the members' own names.",
  rationale: "A dense block of repetitive member comments obscures the few comments that add information and drifts with renamed members.",
  remediation: "Delete comments that restate member names and retain comments that explain constraints, lifecycle, or behavior.",
  category: "maintainability",
  autofix: "safe",
  limitations: ["Automatic fixes remove only an exact multiword member-name comment on its own line and retain all physical line endings; threshold-based or novel prose remains manual.", "Only enum and class bodies meeting the configured comment-count and restatement-ratio thresholds are reported."],
  examples: [
    {
      id: "uncommented-members",
      title: "Let clear member names stand alone",
      outcome: "no-match",
      files: [{ path: "src/status.ts", source: "enum Status { Pending = 'pending', Finished = 'finished', Failed = 'failed' }" }],
      focusPath: "src/status.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "restated-enum-members",
      title: "Do not restate every enum member",
      outcome: "match",
      files: [{ path: "src/status.ts", source: "enum Status {\n  /** The pending status. */\n  Pending = 'pending',\n  /** The finished status. */\n  Finished = 'finished',\n  /** The failed status. */\n  Failed = 'failed',\n}" }],
      focusPath: "src/status.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "class Client {\n  /** Read user. */\n  readUser() {}\n  /** Write user. */\n  writeUser() {}\n  /** Delete user. */\n  deleteUser() {}\n}" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "class Client {\n\n  readUser() {}\n\n  writeUser() {}\n\n  deleteUser() {}\n}" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
