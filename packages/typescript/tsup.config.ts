import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm", "cjs"],
  dts: true,
  sourcemap: true,
  clean: true,
  target: "node24",
  shims: true,
  // Externalize ESLint + its tooling — they live in the host process
  // (the consumer's ESLint instance). Bundling them would (a) break the ESM
  // `Dynamic require of "eslint"` error inside @typescript-eslint/utils, and
  // (b) ship a second copy that can't see the host's rules / configs.
  external: [
    "eslint",
    "typescript",
    "@typescript-eslint/utils",
    "@typescript-eslint/parser",
    "@typescript-eslint/rule-tester",
  ],
});
