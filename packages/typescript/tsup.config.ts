import { defineConfig } from "tsup";

export default defineConfig({
  // The Oxlint plugin, plus the catalog and example verifier that tooling
  // imports from dist/. scripts/oxlint/check-port-bundle.ts proves the plugin
  // bundles no ESLint module.
  entry: {
    index: "src/index.ts",
    catalog: "src/catalog.ts",
    "rule-examples": "src/verify-rule-examples.ts",
    stylelint: "src/stylelint.ts",
  },
  format: ["esm"],
  dts: false,
  sourcemap: false,
  clean: true,
  target: "node22",
  // tsrs loads lazily, only when type-aware rules are on; oxlint and
  // oxc-parser come from the linting process's installation.
  external: ["tsrs", "oxlint", "oxc-parser", "stylelint"],
  // jsonc-parser's ESM build uses extensionless imports Node cannot load.
  noExternal: ["jsonc-parser"],
});
