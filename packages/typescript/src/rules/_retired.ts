/** @fileoverview _retired — burned rule names and their migration action. */

/** Why a name was withdrawn, and in which release. */
export interface RetiredRule {
  /** The plugin version whose release removed the rule. */
  readonly removedIn: string;
  /** One line a consumer can act on: why it went, and what (if anything) replaced it. */
  readonly reason: string;
}

export const RETIRED_RULES: Readonly<Record<string, RetiredRule>> = {
  "ban-loose-type-guards-in-tests": {
    removedIn: "5.0.0",
    reason: "Delete the config entry and suppressions; there is no replacement.",
  },
  "no-implicit-attribute-access": {
    removedIn: "5.0.0",
    reason: "Delete the config entry and suppressions; there is no replacement.",
  },
  "no-async-callback-in-wait-for": {
    removedIn: "14.0.0",
    reason:
      "Delete the entry; Testing Library supports async waitFor callbacks and retries when their promises reject.",
  },
  "no-async-callback-in-waitfor": {
    removedIn: "14.0.0",
    reason:
      "Delete the stale alias; the replacement was also retired because Testing Library supports async waitFor callbacks.",
  },
  "no-conditional-in-test": {
    removedIn: "15.0.0",
    reason:
      "Delete the entry and use a framework plugin only if its broader conditional-test policy is intentional; syntax cannot distinguish weak expectations from valid filtering, discriminant invariants, or implication checks.",
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
  "prefer-single-sentence-comment": {
    removedIn: "10.0.0",
    reason:
      "Delete the config entry and suppressions; use the narrower no-comment-cruft, no-restated-comment, and no-long-comment rules.",
  },
  "prefer-string-literal-union": {
    removedIn: "12.0.0",
    reason:
      "Delete the config entry and suppressions; syntax cannot prove that an open string domain is closed.",
  },
  "prefer-zod-enum": {
    removedIn: "12.0.0",
    reason:
      "Delete the entry; use `zod/prefer-enum-over-literal-union`, which proves every arm is a string literal.",
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
