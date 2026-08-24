/**
 * @fileoverview _renames — every rule this plugin has renamed, old name to new; the old names no longer resolve, so this map is what says what to write instead.
 *
 * `code-standards maintain sync-ledger` turns each entry into the consumer-facing ledger row.
 *
 */

export const RENAMED_RULES = {
  "jsdoc-restates-signature": "no-restated-jsdoc",
  "zod-naming-convention": "require-pascal-case-zod-schema-name",
  "require-interface-for-injected-service": "require-port-for-service",
  "strict-test-assertions": "prefer-whole-object-assertion",
  "trailing-value-narration": "no-trailing-value-narration",
} as const;

export type RenamedFrom = keyof typeof RENAMED_RULES;
export type RenamedTo = (typeof RENAMED_RULES)[RenamedFrom];
