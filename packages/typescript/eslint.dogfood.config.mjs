import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

import sarj, { strictRules } from "./dist/index.js";

const allSarjRules = Object.fromEntries(
  Object.keys(sarj.rules)
    .sort()
    .map((name) => [`@sarj/${name}`, "error"]),
);
const dogfoodRules = { ...allSarjRules, ...strictRules };
const sourceOwnedRejectedExamples = {
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
    plugins: { "@sarj": sarj },
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        projectService: {
          allowDefaultProject: ["*.ts", "*.tsx", "*.mts", "*.cts", "*.mjs"],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: dogfoodRules,
  },
  ...Object.entries(sourceOwnedRejectedExamples).map(([file, rule]) => ({
    name: `sarj/source-owned-rejected-example/${rule}`,
    files: [file],
    rules: { [rule]: "off" },
  })),
);
