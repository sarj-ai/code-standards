/** @fileoverview no-restated-jsdoc — the documentation and executable examples of `@sarj/no-restated-jsdoc`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_RESTATED_JSDOC_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Flag JSDoc prose that appears to repeat declaration names without adding behavioral information.",
  rationale: "Signature-only JSDoc duplicates type information and drifts without helping callers.",
  remediation: "Delete the block or document behavior, constraints, failures, or context the signature cannot express.",
  category: "maintainability",
  aliases: ["jsdoc-restates-signature"],
  autofix: "safe",
  limitations: ["Generated files, detached blocks, intervening comments, unknown tags, explicit JSDoc type payloads, empty blocks, and JSDoc with information absent from the signature are excluded.", "Negation, conditions, constraints, sentinel values, numeric details, and quoted text conservatively preserve the block, even when a declaration name contains the same words."],
  examples: [
    { id: "behavioral-jsdoc", title: "Document behavior absent from the signature", outcome: "no-match", files: [{ path: "src/users.ts", source: "/** Get the user while bypassing the read replica. */\nexport function getUser(id: string) { return id; }" }], focusPath: "src/users.ts", expectedCount: 0, public: true },
    { id: "signature-jsdoc", title: "Remove JSDoc that only repeats the signature", outcome: "match", files: [{ path: "src/users.ts", source: "/** Get the user by id. */\nexport function getUserById(id: string) { return id; }" }], focusPath: "src/users.ts", expectedCount: 1, public: true },
    { id: "negated-behavior", scenarioId: "negation", title: "Keep behavior even when its words resemble the declaration", outcome: "no-match", files: [{ path: "src/users.ts", source: "/** Does not cache the user. */\nexport function cacheUser(user: unknown) { return user; }" }], focusPath: "src/users.ts", expectedCount: 0, public: true },
    { id: "repeated-behavior-name", scenarioId: "negation", title: "Review prose that merely repeats the declaration name", outcome: "match", files: [{ path: "src/users.ts", source: "/** Cache the user. */\nexport function cacheUser(user: unknown) { return user; }" }], focusPath: "src/users.ts", expectedCount: 1, public: true },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "/** Get user. */\nfunction getUser() { return 1; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "\nfunction getUser() { return 1; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
