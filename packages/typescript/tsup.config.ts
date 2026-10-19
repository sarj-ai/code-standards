import { defineConfig } from "tsup";

export default defineConfig({
  entry: { index: "src/index.ts", "rule-examples": "src/verify-rule-examples.ts" },
  format: ["esm", "cjs"],
  dts: true,
  sourcemap: false,
  clean: true,
  target: "node22",
  shims: true,
  external: [
    "eslint",
    "eslint-plugin-sonarjs",
    "typescript",
    "@typescript-eslint/utils",
    "@typescript-eslint/parser",
    "@typescript-eslint/rule-tester",
  ],
});
