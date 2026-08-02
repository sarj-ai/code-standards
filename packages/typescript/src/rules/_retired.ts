/**
 * @fileoverview _retired — a withdrawn rule name is burned, not recycled, because a consumer's `eslint-disable` comment or suppressions entry still names it.
 *
 */

/** Why a name was withdrawn, and in which release. */
export interface RetiredRule {
  /** The plugin version whose release removed the rule. */
  readonly removedIn: string;
  /** One line a consumer can act on: why it went, and what (if anything) replaced it. */
  readonly reason: string;
}

export const retiredRules: Readonly<Record<string, RetiredRule>> = {
  "ban-loose-type-guards-in-tests": {
    removedIn: "5.0.0",
    reason:
      "Read at 39 findings with 0 true positives in the #183 corpus audit. Delete the config entry; no replacement.",
  },
  "no-implicit-attribute-access": {
    removedIn: "5.0.0",
    reason:
      "Read at 50 findings with 0 true positives in the #183 corpus audit. Delete the config entry; no replacement.",
  },
  "no-sequential-await": {
    removedIn: "3.0.0",
    reason:
      "218 findings, 100% range-contained in core `no-await-in-loop`, which the shipped config already enables. Delete the entry; `no-await-in-loop` covers it.",
  },
  "no-template-literal-in-log": {
    removedIn: "2.3.1",
    reason: "Withdrawn. Delete the config entry; no replacement.",
  },
  "no-unsafe-cast": {
    removedIn: "3.0.0",
    reason:
      "1,089 findings, matching `@typescript-eslint/consistent-type-assertions` (\"never\") at the identical line and column with zero residue. Delete the entry; keep that rule enabled.",
  },
  "prefer-setup-file-mocks": {
    removedIn: "5.0.0",
    reason:
      "Read at 50 findings with 0 true positives in the #183 corpus audit. Delete the config entry; no replacement.",
  },
  "prefer-shadcn": {
    removedIn: "3.0.0",
    reason:
      "645 findings, a subset of `react/forbid-elements`; its 24-position residue was all design-system primitives being told not to be the design system. Delete the entry.",
  },
  "primary-export-file-name": {
    removedIn: "4.0.0",
    reason:
      "Renamed files after one of their exports — 316 findings over 1,966 files sampled 11 harmful / 15 useless / 4 valuable, including telling `next.config.ts` to become `next-config.ts`. Delete the config entry.",
  },
  "require-parameterized-tests": {
    removedIn: "4.0.0",
    reason:
      "Landed in #153 and never wired up: absent from the `rules` record, every preset, and eslint.strict.mjs. Nothing to migrate.",
  },
  "require-schema-validate-search": {
    removedIn: "3.0.0",
    reason:
      "14 findings, all matched line-and-column by `@typescript-eslint/consistent-type-assertions`. Delete the entry.",
  },
  "single-public-export": {
    removedIn: "3.0.0",
    reason:
      "3 findings, all also reported by the then-live `primary-export-file-name` (itself withdrawn in 4.0.0). Delete the entry.",
  },
};
