import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import eslintPlugin from "eslint-plugin-eslint-plugin";
import tseslint from "typescript-eslint";

import { MODULE_CONSTANT_NAMING_OPTIONS } from "./module-constant-naming-options.ts";
import noExplicitTypePredicate from "./src/rules/no-explicit-type-predicate.ts";
import noRuntimeTypeof from "./src/rules/no-runtime-typeof.ts";

export default defineConfig(
  { ignores: ["dist/**", "eslint.dogfood.config.ts", "tests/fixtures/**"] },
  {
    name: "sarj/typescript",
    files: ["**/*.{ts,tsx,mts,cts,mjs}"],
    extends: [js.configs.recommended, tseslint.configs.recommendedTypeChecked],
    plugins: { "@sarj": { rules: { "no-explicit-type-predicate": noExplicitTypePredicate, "no-runtime-typeof": noRuntimeTypeof } } },
    languageOptions: {
      parserOptions: {
        projectService: {
          allowDefaultProject: ["*.ts", "*.tsx", "*.mts", "*.cts", "*.mjs"],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    linterOptions: { reportUnusedDisableDirectives: "error" },
    rules: { "@sarj/no-explicit-type-predicate": "error", "@sarj/no-runtime-typeof": "error" },
  },
  {
    name: "sarj/rule-authoring",
    files: ["src/rules/**/*.ts", "tests/rules/**/*.test.ts"],
    extends: [eslintPlugin.configs.recommended],
  },
  {
    name: "sarj/typed-suggestion-report",
    files: ["src/rules/prefer-nullish-filter-predicate.ts"],
    // This rule assigns report.suggest before passing the typed object to context.report.
    rules: { "eslint-plugin/require-meta-has-suggestions": "off" },
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
    // ESTree literal values have native primitive unions; rule implementations
    // also establish raw parser-option contracts without adding a schema dependency.
    rules: {
      "@typescript-eslint/no-unsafe-enum-comparison": "off",
      "@sarj/no-runtime-typeof": "off",
    },
  },
  {
    name: "sarj/module-constant-naming",
    files: ["**/*.{ts,tsx,mts,cts,mjs}"],
    rules: {
      "@typescript-eslint/naming-convention": [
        "error",
        ...MODULE_CONSTANT_NAMING_OPTIONS,
      ],
    },
  },
  {
    name: "sarj/typed-tooling",
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
);
