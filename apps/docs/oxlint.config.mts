import { defineConfig } from "oxlint";

import repositoryTooling from "../../.github/scripts/oxlint.config.mts";
import { SARJ_RULES } from "../../packages/typescript/oxlint.config.mts";

const STRICT_TYPE_CHECKED = [
  "no-useless-constructor",
  "typescript/no-confusing-void-expression",
  "typescript/no-deprecated",
  "typescript/no-dynamic-delete",
  "typescript/no-extraneous-class",
  "typescript/no-generated-empty-object-type",
  "typescript/no-invalid-void-type",
  "typescript/no-meaningless-void-operator",
  "typescript/no-misused-spread",
  "typescript/no-mixed-enums",
  "typescript/no-non-null-asserted-nullish-coalescing",
  "typescript/no-non-null-assertion",
  "typescript/no-unnecessary-boolean-literal-compare",
  "typescript/no-unnecessary-condition",
  "typescript/no-unnecessary-template-expression",
  "typescript/no-unnecessary-type-arguments",
  "typescript/no-unnecessary-type-conversion",
  "typescript/no-unnecessary-type-parameters",
  "typescript/no-unsafe-enum-assignment",
  "typescript/no-useless-default-assignment",
  "typescript/prefer-literal-enum-member",
  "typescript/prefer-reduce-type-parameter",
  "typescript/prefer-return-this-type",
  "typescript/related-getter-setter-pairs",
  "typescript/unified-signatures",
  "typescript/use-unknown-in-catch-callback-variable",
] as const;

const CLIENT_SCRIPT_RULES_ESLINT_NEVER_RAN = {
  "src/components/RuleTable.astro": ["@sarj/no-excessive-cognitive-complexity"],
  "src/components/ThirdPartyRuleList.astro": [
    "@sarj/no-excessive-cognitive-complexity",
    "@sarj/no-raw-fetch-outside-clients",
    "@sarj/no-silent-promise-catch",
  ],
} as const;

export default defineConfig({
  extends: [repositoryTooling],
  jsPlugins: [{ name: "@sarj", specifier: "@sarj/eslint-plugin" }],
  ignorePatterns: [".astro/**", "dist/**"],
  rules: { ...SARJ_RULES },
  overrides: [
    {
      files: ["**/*.{ts,mts,cts}"],
      rules: {
        ...Object.fromEntries(STRICT_TYPE_CHECKED.map((rule) => [rule, "error"])),
        "typescript/ban-ts-comment": ["error", { minimumDescriptionLength: 10 }],
        "typescript/restrict-plus-operands": [
          "error",
          { allowAny: false, allowBoolean: false, allowNullish: false, allowNumberAndString: false, allowRegExp: false },
        ],
        "typescript/restrict-template-expressions": [
          "error",
          { allowAny: false, allowBoolean: false, allowNever: false, allowNullish: false, allowNumber: false, allowRegExp: false },
        ],
        "typescript/return-await": ["error", "error-handling-correctness-only"],
      },
    },
    {
      files: ["**/*.astro"],
      rules: {
        "no-restricted-imports": [
          "error",
          {
            paths: [
              {
                name: "@astrojs/starlight/components",
                importNames: ["Code"],
                message: "Render block code through CodeBlock.astro and the formatted-code projection.",
              },
            ],
          },
        ],
        "@sarj/prefer-shadcn-primitives": "off",
      },
    },
    { files: ["src/components/CodeBlock.astro"], rules: { "no-restricted-imports": "off" } },
    { files: ["src/lib/source-revision.ts"], rules: { "@sarj/no-raw-env": "off" } },
    ...Object.entries(CLIENT_SCRIPT_RULES_ESLINT_NEVER_RAN).map(([file, rules]) => ({
      files: [file],
      rules: Object.fromEntries(rules.map((rule) => [rule, "off" as const])),
    })),
  ],
});
