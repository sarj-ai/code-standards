import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["dist/**", "node_modules/**", "tests/fixtures/**"] },
  {
    name: "sarj/typescript-source",
    files: ["**/*.{js,mjs,cjs,ts,mts,cts}"],
    extends: [js.configs.recommended, tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      parserOptions: {
        projectService: { allowDefaultProject: ["*.ts", "*.mjs"] },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    linterOptions: { reportUnusedDisableDirectives: "error" },
    rules: {
      // ESTree discriminants intentionally interoperate with enum members and string literals.
      "@typescript-eslint/no-unsafe-enum-comparison": "off",
    },
  },
);
