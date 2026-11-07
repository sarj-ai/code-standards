/** @fileoverview no-type-member-comment-wall — the documentation and executable examples of `@sarj/no-type-member-comment-wall`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_TYPE_MEMBER_COMMENT_WALL_DOCUMENTATION = {
  summary: "Flag an object type whose member comments mostly re-spell the members' own names and types.",
  rationale: "Repetitive member comments add scanning cost while hiding the comments that describe facts absent from the type.",
  remediation: "Delete comments that restate member names or types and keep comments that add constraints or behavior.",
  category: "maintainability",
  autofix: "safe",
  limitations: ["Automatic fixes remove only an exact multiword member-name comment on its own line and retain all physical line endings; threshold-based or novel prose remains manual.", "Only interface and type-literal bodies meeting the configured comment-count and restatement-ratio thresholds are reported. Negation, requirements, conditional relations, and fixed-value contracts are not counted as restatements. The novel-word threshold is a review heuristic, not proof that a comment contains no useful contract."],
  examples: [
    {
      id: "uncommented-members",
      title: "Let clear member names and types stand alone",
      outcome: "no-match",
      files: [{ path: "src/credentials.ts", source: "interface Credentials { host?: string; port?: number; username?: string; password?: string; }" }],
      focusPath: "src/credentials.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "restated-type-members",
      title: "Do not restate member names and types",
      outcome: "match",
      files: [{ path: "src/credentials.ts", source: "interface Credentials {\n  // Database host.\n  host?: string;\n  // Database host port.\n  port?: number;\n  // Database username.\n  username?: string;\n  // Database password.\n  password?: string;\n}" }],
      focusPath: "src/credentials.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "interface Client {\n  /** Read user. */\n  readUser(): void;\n  /** Write user. */\n  writeUser(): void;\n  /** Delete user. */\n  deleteUser(): void;\n}" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "interface Client {\n\n  readUser(): void;\n\n  writeUser(): void;\n\n  deleteUser(): void;\n}" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
