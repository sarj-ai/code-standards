import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

import sarj, { STRICT_RULES } from "./dist/index.js";
import { MODULE_CONSTANT_NAMING_OPTIONS } from "./module-constant-naming-options.mjs";

const ALL_SARJ_RULES = Object.fromEntries(
  Object.keys(sarj.rules)
    .sort()
    .map((name) => [`@sarj/${name}`, "error"]),
);
const DOGFOOD_RULES = { ...ALL_SARJ_RULES, ...STRICT_RULES };
const SOURCE_OWNED_REJECTED_EXAMPLES = {
  "src/rules/no-dynamic-sql.ts": "@sarj/no-select-star",
  "src/rules/no-offset-pagination.ts": "@sarj/no-offset-pagination",
  "src/rules/no-select-star.ts": "@sarj/no-select-star",
  "src/rules/store-insert-requires-on-conflict.ts": "@sarj/store-insert-requires-on-conflict",
};

export default defineConfig(
  { ignores: ["dist/**", "tests/fixtures/**"] },
  {
    name: "sarj/all-custom-rules-dogfood",
    files: ["**/*.{ts,tsx,mts,cts,mjs}"],
    plugins: { "@sarj": sarj, "@typescript-eslint": tseslint.plugin },
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
      "@typescript-eslint/naming-convention": ["error", ...MODULE_CONSTANT_NAMING_OPTIONS],
    },
  },
  ...Object.entries(SOURCE_OWNED_REJECTED_EXAMPLES).map(([file, rule]) => ({
    name: `sarj/source-owned-rejected-example/${rule}`,
    files: [file],
    rules: { [rule]: "off" },
  })),
);
