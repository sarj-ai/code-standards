import { defineConfig } from "vitest/config";

export default defineConfig({
  // `tests/strict-config-loads.test.ts` imports the shipped eslint.strict.mjs,
  // which imports "@sarj/eslint-plugin" — this package, by its published name.
  // Aliasing it to the working-tree source means the config-loading guard runs
  // against the rules as they are NOW, with no `npm run build` in front of
  // `npm test` and no risk of validating a stale dist/.
  resolve: {
    alias: {
      "@sarj/eslint-plugin": new URL("./src/index.ts", import.meta.url).pathname,
    },
  },
  test: {
    include: ["tests/**/*.test.ts"],
    globals: false,
  },
});
