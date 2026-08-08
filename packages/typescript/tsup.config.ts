import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm", "cjs"],
  dts: true,
  sourcemap: false,
  clean: true,
  target: "node22",
  shims: true,
  external: [
    "eslint",
    "typescript",
    "@typescript-eslint/utils",
    "@typescript-eslint/parser",
    "@typescript-eslint/rule-tester",
  ],
});
