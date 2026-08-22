import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

import { MODULE_CONSTANT_NAMING_OPTIONS } from "./eslint.naming-options.mjs";

export default defineConfig(
  { ignores: ["dist/**", "eslint.dogfood.config.mjs", "tests/fixtures/**"] },
  {
    name: "sarj/typescript",
    files: ["**/*.{ts,tsx,mts,cts,mjs}"],
    extends: [js.configs.recommended, tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      parserOptions: {
        projectService: {
          allowDefaultProject: ["*.ts", "*.tsx", "*.mts", "*.cts", "*.mjs"],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    linterOptions: { reportUnusedDisableDirectives: "error" },
  },
  {
    name: "sarj/javascript",
    files: ["**/*.{js,cjs}"],
    extends: [js.configs.recommended],
    linterOptions: { reportUnusedDisableDirectives: "error" },
  },
  {
    name: "sarj/estree-discriminants",
    files: ["src/rules/**/*.{ts,tsx,mts,cts}"],
    rules: { "@typescript-eslint/no-unsafe-enum-comparison": "off" },
  },
  {
    name: "sarj/module-constant-naming",
    files: ["**/*.{ts,tsx,mts,cts,mjs}"],
    rules: {
      "@typescript-eslint/naming-convention": ["error", ...MODULE_CONSTANT_NAMING_OPTIONS],
    },
  },
);
