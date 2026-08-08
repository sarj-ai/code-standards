import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

import sarj, { strictRules } from "./dist/index.js";

const allSarjRules = Object.fromEntries(
  Object.keys(sarj.rules)
    .sort()
    .map((name) => [`@sarj/${name}`, "error"]),
);
const dogfoodRules = { ...allSarjRules, ...strictRules };

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
);
