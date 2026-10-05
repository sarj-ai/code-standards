import { defineConfig } from "tsup";

export default defineConfig([
  {
    entry: {
      index: "src/index.ts",
      config: "src/create-strict-oxlint-config.ts",
      presets: "src/native-presets.ts",
      "rule-examples": "src/verify-rule-examples.ts",
      "select-rules": "src/create-selected-oxlint-config.ts",
    },
    format: ["esm"],
    dts: true,
    sourcemap: false,
    clean: true,
    target: "node22",
    shims: true,
    external: ["@oxlint/plugins", "oxlint", "oxc-parser"],
  },
  {
    entry: {
      ...Object.fromEntries(
        [
          "unicorn",
          "perfectionist",
          "simple-import-sort",
          "zod",
          "node-test",
          "react",
          "core",
          "jsdoc",
          "typescript",
          "playwright",
          "testing-library",
          "bun",
          "node",
          "astro",
          "query",
          "nextjs",
          "test",
          "sonarjs",
        ].map((family) => [`upstream/${family}`, `src/upstream/${family}.js`]),
      ),
      "framework/astro": "src/framework/astro.mjs",
      "framework/astro-cli": "src/framework/astro-cli.mjs",
    },
    format: ["esm"],
    dts: false,
    esbuildOptions(options, { format }) {
      if (format === "esm")
        options.banner = {
          js: 'import { createRequire as createRequireFromModule } from "node:module"; const require = createRequireFromModule(import.meta.url);',
        };
    },
    clean: false,
    target: "node22",
    shims: true,
  },
]);
