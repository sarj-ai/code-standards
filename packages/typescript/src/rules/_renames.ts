/**
 * @fileoverview _renames — a renamed rule keeps its old name registered as a deprecated alias, because a name that simply vanishes reads as growth to a shrink-only baseline.
 *
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/_renames.md
 */

export const renamedRules = {
  "jsdoc-restates-signature": "no-restated-jsdoc",
  "no-async-callback-in-waitfor": "no-async-callback-in-wait-for",
  "strict-test-assertions": "prefer-whole-object-assertion",
  "trailing-value-narration": "no-trailing-value-narration",
} as const;

export type RenamedFrom = keyof typeof renamedRules;
export type RenamedTo = (typeof renamedRules)[RenamedFrom];
