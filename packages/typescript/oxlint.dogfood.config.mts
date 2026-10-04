import { defineConfig } from "oxlint";
import plugin, { strictRules } from "./dist/index.js";

const allRules = Object.fromEntries(Object.keys(plugin.rules).map((name) => [`@sarj/${name}`, "error"]));

export default defineConfig({
  plugins: ["oxc"],
  jsPlugins: [{ name: "@sarj", specifier: "./dist/index.js" }],
  ignorePatterns: ["dist/**", "tests/fixtures/**"],
  rules: { ...allRules, ...strictRules, "oxc/no-accumulating-spread": "error" },
  overrides: [
    { files: ["src/rules/no-dynamic-sql.ts", "src/rules/no-select-star.ts"], rules: { "@sarj/no-select-star": "off" } },
    { files: ["src/rules/no-offset-pagination.ts"], rules: { "@sarj/no-offset-pagination": "off" } },
    { files: ["src/rules/store-insert-requires-on-conflict.ts"], rules: { "@sarj/store-insert-requires-on-conflict": "off" } },
  ],
});
