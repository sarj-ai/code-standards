import { defineConfig, type DummyRuleMap, type OxlintOverride } from "oxlint";

import sarj from "@sarj/eslint-plugin";

import repositoryTooling from "../../.github/scripts/oxlint.config.mts";
import { LIBRARY_POLICY } from "./src/library-policy.ts";

// The package's own gate (`npm run lint`, also `make dogfood`): the
// repository tooling rules (ESLint and typescript-eslint recommended, as native
// Oxlint ports) plus every @sarj rule from the built plugin at error, the
// zero-diagnostic dogfood. Type-aware rules run through tsrs; `npm run
// typecheck` runs the type check itself.
//
// This package defines the managed preset (oxlint.strict.mts) and does not
// extend it: the preset's style rules were never this repository's policy.
// typescript-eslint's naming-convention has no Oxlint port, so there is no
// SCREAMING_SNAKE_CASE module-constant check.

// The options the managed preset gives these rules; the rest take their
// defaults. The directive rules carry the Standards floor's options.
const SARJ_OPTIONS: Readonly<DummyRuleMap> = {
  "@sarj/directive-disable-enable-pair": ["error", { allowWholeFile: false }],
  "@sarj/directive-no-restricted-disable": [
    "error",
    "@sarj/directive-*",
    "@sarj/no-oxlint-directive",
    "@sarj/no-vague-suppression-description",
    "typescript/ban-ts-comment",
  ],
  "@sarj/directive-no-use": [
    "error",
    {
      allow: [
        "eslint-disable-line",
        "eslint-disable-next-line",
        "eslint-env",
        "exported",
        "global",
        "globals",
      ],
    },
  ],
  "@sarj/directive-require-description": ["error", { ignore: [] }],
  "@sarj/no-fat-try-blocks": ["error", { max: 5 }],
  "@sarj/no-impossible-zod-literal-bounds": ["error", { delegateRealContradictions: true }],
  "@sarj/no-restricted-library-load": ["error", { libraries: LIBRARY_POLICY }],
  "@sarj/no-unlocalized-jsx-attributes": ["error", { enabled: false }],
  "@sarj/no-unlocalized-jsx-text": ["error", { enabled: false }],
  "@sarj/no-unlocalized-toast": ["error", { enabled: false }],
  "@sarj/prefer-await-in-async-return": ["error", { scope: "all-promise-calls" }],
  "@sarj/prefer-logical-tailwind-utilities": ["error", { enabled: false }],
  "@sarj/prefer-multi-value-zod-literal": ["error", { zodMajorVersion: 4 }],
  "@sarj/prefer-semantic-colors": ["error", { requireSemanticTokens: true }],
  "@sarj/stepdown": ["error", { privateBandOnly: true }],
};

/** Every @sarj rule at error, as apps/docs also runs them. */
export const SARJ_RULES: Readonly<DummyRuleMap> = {
  ...Object.fromEntries(Object.keys(sarj.rules).map((rule) => [`@sarj/${rule}`, "error"])),
  ...SARJ_OPTIONS,
};

// Rule sources and their documentation hold the very patterns a rule rejects.
const SOURCE_OWNED_REJECTED_EXAMPLES: readonly OxlintOverride[] = ["src/rules", "src/docs"].flatMap(
  (directory) => [
    {
      files: [`${directory}/no-dynamic-sql.ts`, `${directory}/no-select-star.ts`],
      rules: { "@sarj/no-select-star": "off" },
    },
    {
      files: [`${directory}/no-offset-pagination.ts`],
      rules: { "@sarj/no-offset-pagination": "off" },
    },
    {
      files: [`${directory}/store-insert-requires-on-conflict.ts`],
      rules: { "@sarj/store-insert-requires-on-conflict": "off" },
    },
  ],
);

export default defineConfig({
  extends: [repositoryTooling],
  jsPlugins: [{ name: "@sarj", specifier: "@sarj/eslint-plugin" }],
  // Upstream bundles are generated and hash-verified by build-upstream.ts.
  ignorePatterns: ["dist/**", "tests/fixtures/**", "src/upstream/**"],
  rules: { ...SARJ_RULES },
  overrides: [
    ...SOURCE_OWNED_REJECTED_EXAMPLES,
    {
      // Rule implementations and the documentation validator read raw ESTree
      // literals and rule options, whose primitive unions are the contract.
      files: ["src/rules/**", "src/utils/**", "src/types.ts", "src/documentation.ts"],
      rules: { "@sarj/no-runtime-typeof": "off", "typescript/no-unsafe-enum-comparison": "off" },
    },
    {
      // Each module exports one `<RULE>_DOCUMENTATION` constant for the generated index.
      files: ["src/docs/**"],
      rules: { "@sarj/sole-export-matches-filename": "off" },
    },
  ],
});
