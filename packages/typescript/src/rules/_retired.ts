/** @fileoverview _retired — burned rule names and their migration action. */

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
    reason: "Delete the config entry and suppressions; there is no replacement.",
  },
  "no-implicit-attribute-access": {
    removedIn: "5.0.0",
    reason: "Delete the config entry and suppressions; there is no replacement.",
  },
  "no-sequential-await": {
    removedIn: "3.0.0",
    reason: "Delete the entry; core `no-await-in-loop` covers it.",
  },
  "no-template-literal-in-log": {
    removedIn: "2.3.1",
    reason: "Delete the config entry and suppressions; there is no replacement.",
  },
  "no-unsafe-cast": {
    removedIn: "3.0.0",
    reason: "Delete the entry; keep `@typescript-eslint/consistent-type-assertions` enabled.",
  },
  "prefer-setup-file-mocks": {
    removedIn: "5.0.0",
    reason: "Delete the config entry and suppressions; there is no replacement.",
  },
  "prefer-shadcn": {
    removedIn: "3.0.0",
    reason:
      "Delete the retired entry; application-profile consumers can separately adopt `@sarj/prefer-shadcn-primitives`.",
  },
  "primary-export-file-name": {
    removedIn: "4.0.0",
    reason: "Delete the config entry and suppressions; there is no replacement.",
  },
  "require-parameterized-tests": {
    removedIn: "4.0.0",
    reason: "Delete stale references; the rule was never registered.",
  },
  "require-schema-validate-search": {
    removedIn: "3.0.0",
    reason: "Delete the entry; use `@typescript-eslint/consistent-type-assertions`.",
  },
  "single-public-export": {
    removedIn: "3.0.0",
    reason: "Delete the config entry and suppressions; there is no replacement.",
  },
};
