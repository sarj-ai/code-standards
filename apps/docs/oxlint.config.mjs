import { defineConfig } from "oxlint";
import { fileURLToPath } from "node:url";
import plugin, { strictRules } from "@sarj/oxlint-plugin";
import {
  RECOMMENDED_RULES,
  TYPESCRIPT_STRICT_RULES,
  TYPESCRIPT_COMPATIBILITY_OVERRIDE,
} from "@sarj/oxlint-plugin/presets";

const allSarjRules = Object.fromEntries(
  Object.keys(plugin.rules).map((name) => {
    const id = `@sarj/${name}`;
    const configured = strictRules[id];
    return [id, Array.isArray(configured) ? ["error", ...configured.slice(1)] : "error"];
  }),
);

export default defineConfig({
  plugins: ["eslint", "typescript", "oxc"],
  categories: { correctness: "off" },
  jsPlugins: [
    {
      name: "sarj-core",
      specifier: fileURLToPath(import.meta.resolve("@sarj/oxlint-plugin/upstream/core")),
    },
    { name: "@sarj", specifier: fileURLToPath(import.meta.resolve("@sarj/oxlint-plugin")) },
    {
      name: "sarj-astro",
      specifier: fileURLToPath(import.meta.resolve("@sarj/oxlint-plugin/upstream/astro")),
    },
  ],
  ignorePatterns: [".astro/**", "dist/**", "scripts/vendor/**"],
  env: { node: true, es2024: true },
  options: {
    typeAware: true,
    reportUnusedDisableDirectives: "error",
    respectEslintDisableDirectives: false,
  },
  rules: { ...RECOMMENDED_RULES },
  overrides: [
    {
      files: ["**/*.{ts,mts,cts}"],
      rules: { ...TYPESCRIPT_COMPATIBILITY_OVERRIDE.rules, ...TYPESCRIPT_STRICT_RULES },
    },
    {
      files: ["**/*.{astro,ts,mts,cts,mjs}"],
      rules: allSarjRules,
    },
    {
      files: ["**/*.astro"],
      env: { node: true, astro: true },
      rules: {
        "sarj-astro/missing-client-only-directive-value": "error",
        "sarj-astro/no-conflict-set-directives": "error",
        "sarj-astro/no-unused-define-vars-in-style": "error",
        "sarj-astro/no-deprecated-astro-canonicalurl": "error",
        "sarj-astro/no-deprecated-astro-fetchcontent": "error",
        "sarj-astro/no-deprecated-astro-resolve": "error",
        "sarj-astro/no-deprecated-getentrybyslug": "error",
        "sarj-astro/no-exports-from-components": "error",
        "sarj-astro/no-prerender-export-outside-pages": "error",
        "eslint/no-restricted-imports": [
          "error",
          {
            paths: [
              {
                name: "@astrojs/starlight/components",
                importNames: ["Code"],
                message:
                  "Render block code through CodeBlock.astro and the formatted-code projection.",
              },
            ],
          },
        ],
        "@sarj/prefer-shadcn-primitives": "off",
      },
    },
    {
      files: ["src/components/CodeBlock.astro"],
      rules: { "eslint/no-restricted-imports": "off" },
    },
  ],
});
