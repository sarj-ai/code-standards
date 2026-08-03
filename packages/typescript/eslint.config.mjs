import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["dist/**", "tests/fixtures/**"] },
  {
    name: "sarj/typescript",
    files: ["**/*.{ts,mjs}"],
    extends: [js.configs.recommended, tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      parserOptions: {
        projectService: { allowDefaultProject: ["*.ts", "*.mjs"] },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    linterOptions: { reportUnusedDisableDirectives: "error" },
  },
  {
    name: "sarj/estree-discriminants",
    files: ["src/rules/**/*.ts"],
    rules: { "@typescript-eslint/no-unsafe-enum-comparison": "off" },
  },
);
