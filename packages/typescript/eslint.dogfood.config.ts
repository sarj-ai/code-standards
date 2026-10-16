import type { TSESLint } from "@typescript-eslint/utils";
import tseslint from "typescript-eslint";

import sarj, { STRICT_RULES } from "./dist/index.js";
import { eslintRuleSetting } from "./eslint-rule-setting.ts";
import { MODULE_CONSTANT_NAMING_OPTIONS } from "./module-constant-naming-options.ts";

const ALL_SARJ_RULES = Object.fromEntries(
  Object.keys(sarj.rules)
    .sort()
    .map((name) => [`@sarj/${name}`, "error"]),
);
const DOGFOOD_RULES = Object.fromEntries(
  Object.entries({ ...ALL_SARJ_RULES, ...STRICT_RULES }).map(
    ([id, setting]) => [id, eslintRuleSetting(setting)],
  ),
);
const SOURCE_OWNED_REJECTED_EXAMPLES = {
  "src/rules/no-dynamic-sql.ts": "@sarj/no-select-star",
  "src/rules/no-offset-pagination.ts": "@sarj/no-offset-pagination",
  "src/rules/no-select-star.ts": "@sarj/no-select-star",
  "src/rules/store-insert-requires-on-conflict.ts":
    "@sarj/store-insert-requires-on-conflict",
} as const;

export default Object.freeze<TSESLint.FlatConfig.ConfigArray>([
  { ignores: ["dist/**", "tests/fixtures/**"] },
  {
    name: "sarj/all-custom-rules-dogfood",
    files: ["**/*.{ts,tsx,mts,cts,mjs}"],
    plugins: {
      "@sarj": { meta: sarj.meta, rules: sarj.rules },
      "@typescript-eslint": tseslint.plugin,
    },
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        projectService: {
          allowDefaultProject: ["*.ts", "*.tsx", "*.mts", "*.cts", "*.mjs"],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      ...DOGFOOD_RULES,
      "@typescript-eslint/naming-convention": [
        "error",
        ...MODULE_CONSTANT_NAMING_OPTIONS,
      ],
    },
  },
  {
    files: [
      "scripts/**/*.ts",
      "eslint.config.ts",
      "eslint.dogfood.config.ts",
      "module-constant-naming-options.ts",
      "eslint-rule-setting.ts",
    ],
    languageOptions: {
      parserOptions: {
        projectService: false,
        project: "./tsconfig.tools.json",
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  ...Object.entries(SOURCE_OWNED_REJECTED_EXAMPLES).map(([file, rule]) => ({
    name: `sarj/source-owned-rejected-example/${rule}`,
    files: [file],
    rules: { [rule]: "off" as const },
  })),
]);
