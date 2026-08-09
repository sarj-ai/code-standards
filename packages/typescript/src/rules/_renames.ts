/**
 * @fileoverview _renames — every rule this plugin has renamed, old name to new; the old names no longer resolve, so this map is what says what to write instead.
 *
 * `sarj-standards maintain sync-ledger` turns each entry into the consumer-facing ledger row.
 *
 */

export const renamedRules = {
  "jsdoc-restates-signature": "no-restated-jsdoc",
  "require-interface-for-injected-service": "require-port-for-service",
  "strict-test-assertions": "prefer-whole-object-assertion",
  "trailing-value-narration": "no-trailing-value-narration",
} as const;

export type RenamedFrom = keyof typeof renamedRules;
export type RenamedTo = (typeof renamedRules)[RenamedFrom];
