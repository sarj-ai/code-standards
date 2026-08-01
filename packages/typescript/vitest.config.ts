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
    // A timeout is a hang watchdog, not a performance budget — the budgets live
    // in `tests/perf.test.ts` and are ratios, not wall clock. Vitest's 5 s
    // default is below what a COLD type-aware program build costs inside
    // `@typescript-eslint/rule-tester`, so eight test files failed with
    // "Test timed out in 5000ms" in a full parallel run and passed one at a
    // time — a failure that says nothing about the code under test. Raising the
    // watchdog is the fix; raising a budget would not have been.
    testTimeout: 60_000,
    hookTimeout: 60_000,
  },
});
