import { defineConfig } from "oxlint";

export default defineConfig({
  plugins: ["typescript", "oxc"],
  categories: { correctness: "error" },
  ignorePatterns: ["dist/**", "tests/fixtures/**"],
  options: { typeAware: true, reportUnusedDisableDirectives: "error" },
  rules: { "oxc/no-accumulating-spread": "error" },
});
