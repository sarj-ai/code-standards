import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@sarj/eslint-plugin": new URL("./src/index.ts", import.meta.url).pathname,
    },
  },
  test: {
    include: ["tests/**/*.test.ts"],
    globals: false,
    testTimeout: 60_000,
    hookTimeout: 60_000,
  },
});
