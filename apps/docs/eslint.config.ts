import type { TSESLint } from "@typescript-eslint/utils";
import js from "@eslint/js";
import sarj from "@sarj/eslint-plugin";
import { eslintRuleSetting } from "../../packages/typescript/eslint-rule-setting.ts";
import astro from "eslint-plugin-astro";
import tseslint from "typescript-eslint";

const strictRuleSettings = new Map(Object.entries(sarj.configs.strict.rules));

const allSarjRules = Object.fromEntries(
  Object.keys(sarj.rules)
    .sort()
    .map((name) => {
      const id = `@sarj/${name}`;
      const configured = eslintRuleSetting(strictRuleSettings.get(id));
      // Preserve policy options when escalating the shared preset for dogfooding.
      return [
        id,
        eslintRuleSetting(
          typeof configured === "string" || typeof configured === "number"
            ? "error"
            : ["error", ...configured.slice(1)],
        ),
      ];
    }),
);

export default Object.freeze<TSESLint.FlatConfig.ConfigArray>([
  { ignores: [".astro/**", "dist/**"] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked.map((config) => ({
    ...config,
    files: ["**/*.{ts,mts,cts}"],
  })),
  {
    files: ["**/*.{ts,mts,cts}"],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  ...astro.configs["flat/recommended"],
  {
    files: ["**/*.{astro,ts,mts,cts,mjs}"],
    plugins: { "@sarj": { meta: sarj.meta, rules: sarj.rules } },
    rules: allSarjRules,
  },
  {
    files: ["**/*.astro"],
    rules: {
      "no-restricted-imports": [
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
      // This React/shadcn policy is inapplicable to framework-native Astro markup.
      "@sarj/prefer-shadcn-primitives": "off",
    },
  },
  {
    files: ["src/components/CodeBlock.astro"],
    rules: { "no-restricted-imports": "off" },
  },
]);
