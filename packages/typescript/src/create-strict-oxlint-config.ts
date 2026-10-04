import { readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import globals from "globals";
import { defineConfig, type OxlintConfig } from "oxlint";
import { strictRules } from "./index.js";
import { LIBRARY_IMPORT_RESTRICTIONS } from "./library-policy.js";
import { UPSTREAM_RULES, UPSTREAM_OVERRIDES } from "./upstream-policy.js";
import {
  RECOMMENDED_RULES,
  TYPESCRIPT_PRESET_RULES,
  TYPESCRIPT_COMPATIBILITY_OVERRIDE,
  TYPE_AWARE_RULE_IDS,
  TANSTACK_QUERY_RECOMMENDED_RULES,
  NEXTJS_ADDITIONAL_RECOMMENDED_RULES,
  SONARJS_ADDITIONAL_RULES,
} from "./native-presets.js";

const NATIVE_RULES = Object.freeze({
  "eslint/no-async-promise-executor": "error",
  "eslint/no-constant-binary-expression": "error",
  "eslint/no-unsafe-finally": "error",
  "eslint/no-unsafe-optional-chaining": "error",
  "typescript/no-explicit-any": "error",
  "typescript/no-non-null-assertion": "error",
  "typescript/no-deprecated": "error",
  "typescript/only-throw-error": [
    "error",
    {
      allow: [
        {
          from: "package",
          package: "@tanstack/react-router",
          name: ["redirect"],
        },
      ],
    },
  ],
  "typescript/prefer-promise-reject-errors": "error",
  "typescript/no-meaningless-void-operator": "error",
  "typescript/no-mixed-enums": "error",
  "typescript/strict-void-return": "warn",
  "vitest/no-conditional-expect": "off",
  "jest/no-conditional-expect": "off",
  "sarj-test/no-conditional-expect": "warn",
  "typescript/prefer-find": "error",
  "typescript/prefer-readonly": "error",
  "typescript/no-unsafe-assignment": "error",
  "typescript/no-unsafe-member-access": "error",
  "typescript/no-unsafe-argument": "error",
  "typescript/no-unsafe-call": "error",
  "typescript/no-unsafe-return": "error",
  "typescript/no-floating-promises": [
    "error",
    {
      ignoreVoid: false,
    },
  ],
  "typescript/await-thenable": "error",
  "typescript/no-misused-promises": [
    "error",
    { checksVoidReturn: { attributes: false } },
  ],
  "promise/prefer-await-to-then": "off",
  "typescript/require-await": "error",
  "typescript/no-inferrable-types": "off",
  "eslint/no-unused-vars": [
    "error",
    {
      argsIgnorePattern: "^_",
      varsIgnorePattern: "^_",
      caughtErrorsIgnorePattern: "^_",
      ignoreRestSiblings: true,
    },
  ],
  "typescript/consistent-indexed-object-style": ["error", "record"],
  "typescript/consistent-type-imports": [
    "error",
    {
      prefer: "type-imports",
      fixStyle: "inline-type-imports",
    },
  ],
  "typescript/consistent-type-exports": [
    "error",
    {
      fixMixedExportsWithInlineTypeSpecifier: true,
    },
  ],
  "typescript/switch-exhaustiveness-check": "error",
  "typescript/consistent-type-assertions": [
    "error",
    {
      assertionStyle: "never",
    },
  ],
  "typescript/prefer-as-const": "error",
  "typescript/no-unnecessary-condition": "error",
  "typescript/prefer-nullish-coalescing": [
    "error",
    {
      ignorePrimitives: {
        number: true,
        string: true,
        boolean: true,
      },
    },
  ],
  "typescript/prefer-optional-chain": "error",
  "typescript/promise-function-async": "off",
  "typescript/no-confusing-void-expression": [
    "error",
    {
      ignoreArrowShorthand: true,
    },
  ],
  "typescript/no-non-null-asserted-optional-chain": "error",
  "typescript/no-unnecessary-type-assertion": "error",
  "typescript/no-redundant-type-constituents": "error",
  "typescript/require-array-sort-compare": "error",
  "typescript/no-unsafe-type-assertion": "error",
  "typescript/no-unsafe-enum-comparison": "error",
  "typescript/no-base-to-string": "error",
  "typescript/no-misused-spread": "error",
  "typescript/no-unnecessary-type-conversion": "error",
  "typescript/prefer-includes": "error",
  "typescript/prefer-string-starts-ends-with": "error",
  "typescript/no-confusing-non-null-assertion": "error",
  "typescript/no-duplicate-type-constituents": "error",
  "typescript/no-invalid-void-type": "error",
  "typescript/no-unnecessary-template-expression": "error",
  "typescript/no-import-type-side-effects": "error",
  "typescript/no-unnecessary-qualifier": "error",
  "typescript/no-useless-empty-export": "error",
  "typescript/array-type": "error",
  "eslint/default-param-last": "error",
  "eslint/prefer-object-has-own": "error",
  "react/no-unstable-nested-components": "off",
  "react/exhaustive-deps": "error",
  "react/rules-of-hooks": "error",
  "react/error-boundaries": "error",
  "react/globals": "error",
  "react/immutability": "error",
  "react/incompatible-library": "error",
  "react/preserve-manual-memoization": "error",
  "react/purity": "error",
  "react/refs": "error",
  "react/set-state-in-effect": "error",
  "react/set-state-in-render": "error",
  "react/static-components": "error",
  "react/unsupported-syntax": "error",
  "react/use-memo": "error",
  "react/void-use-memo": "error",
  "react/forbid-component-props": "off",
  "react/forbid-dom-props": "off",
  "react/jsx-pascal-case": "error",
  "react/no-danger": "error",
  "react/no-this-in-sfc": "error",
  "react/jsx-no-comment-textnodes": "error",
  "react/jsx-no-duplicate-props": "error",
  "react/jsx-no-target-blank": "error",
  "react/jsx-no-undef": "error",
  "react/no-object-type-as-default-prop": "error",
  "react/no-unknown-property": "error",
  "react/void-dom-elements-no-children": "error",
  "react/jsx-fragments": "error",
  "react/jsx-no-script-url": "error",
  "react/self-closing-comp": "error",
  "react/jsx-no-useless-fragment": "error",
  "react/jsx-key": "error",
  "react/no-children-prop": "error",
  "react/style-prop-object": "error",
  "react/button-has-type": "error",
  "react/jsx-boolean-value": ["error", "never"],
  "react/jsx-curly-brace-presence": [
    "error",
    {
      props: "never",
      children: "never",
      propElementValues: "always",
    },
  ],
  "unicorn/consistent-function-scoping": "error",
  "unicorn/filename-case": [
    "error",
    {
      cases: {
        kebabCase: true,
      },
      ignore: ["^__root\\.", "^_", "^\\$", "^\\+", "\\.gen\\."],
    },
  ],
  "unicorn/no-useless-undefined": "off",
  "unicorn/prefer-node-protocol": "error",
  "unicorn/prefer-string-replace-all": "error",
  "unicorn/prefer-top-level-await": "off",
  "unicorn/no-await-expression-member": "error",
  "unicorn/prefer-structured-clone": "error",
  "unicorn/prefer-logical-operator-over-ternary": "off",
  "unicorn/relative-url-style": ["error", "never"],
  "unicorn/throw-new-error": "error",
  "unicorn/consistent-assert": "error",
  "unicorn/consistent-date-clone": "error",
  "unicorn/consistent-empty-array-spread": "error",
  "unicorn/error-message": "error",
  "unicorn/explicit-timer-delay": "error",
  "unicorn/new-for-builtins": "error",
  "unicorn/no-accessor-recursion": "error",
  "unicorn/no-array-fill-with-reference-type": "error",
  "unicorn/no-array-method-this-argument": "error",
  "unicorn/no-await-in-promise-methods": "error",
  "unicorn/no-confusing-array-with": "error",
  "unicorn/no-document-cookie": "error",
  "unicorn/no-empty-file": "error",
  "unicorn/no-immediate-mutation": "error",
  "unicorn/no-instanceof-builtins": "error",
  "unicorn/no-invalid-fetch-options": "off",
  "unicorn/no-invalid-remove-event-listener": "error",
  "unicorn/no-magic-array-flat-depth": "error",
  "unicorn/no-negation-in-equality-check": "error",
  "unicorn/no-new-array": "error",
  "unicorn/no-new-buffer": "error",
  "unicorn/no-object-as-default-parameter": "error",
  "unicorn/no-single-promise-in-promise-methods": "error",
  "unicorn/no-thenable": "off",
  "unicorn/no-this-assignment": "error",
  "unicorn/no-typeof-undefined": "error",
  "unicorn/no-unnecessary-array-flat-depth": "error",
  "unicorn/no-unnecessary-array-splice-count": "error",
  "unicorn/no-unnecessary-await": "error",
  "unicorn/no-unnecessary-slice-end": "error",
  "unicorn/no-useless-collection-argument": "error",
  "unicorn/no-useless-error-capture-stack-trace": "error",
  "unicorn/no-useless-fallback-in-spread": "error",
  "unicorn/no-useless-iterator-to-array": "error",
  "unicorn/no-useless-length-check": "error",
  "unicorn/no-useless-promise-resolve-reject": "error",
  "unicorn/no-useless-spread": "off",
  "unicorn/no-useless-switch-case": "off",
  "unicorn/prefer-add-event-listener": "error",
  "unicorn/prefer-keyboard-event-key": "error",
  "unicorn/require-array-join-separator": "error",
  "unicorn/require-module-attributes": "error",
  "unicorn/require-module-specifiers": "off",
  "unicorn/require-number-to-fixed-digits-argument": "error",
  "unicorn/require-post-message-target-origin": "error",
  "unicorn/text-encoding-identifier-case": "error",
  "unicorn/no-array-reverse": "error",
  "unicorn/no-array-sort": "error",
  "unicorn/prefer-array-flat": "error",
  "unicorn/prefer-array-flat-map": "error",
  "unicorn/prefer-array-index-of": "error",
  "unicorn/prefer-array-some": "error",
  "unicorn/prefer-at": "error",
  "unicorn/prefer-bigint-literals": "error",
  "unicorn/prefer-blob-reading-methods": "error",
  "unicorn/prefer-class-fields": "error",
  "unicorn/prefer-code-point": "error",
  "unicorn/prefer-date-now": "error",
  "unicorn/prefer-default-parameters": "error",
  "unicorn/prefer-event-target": "error",
  "unicorn/prefer-export-from": "error",
  "unicorn/prefer-import-meta-properties": "error",
  "unicorn/prefer-math-min-max": "error",
  "unicorn/prefer-math-trunc": "error",
  "unicorn/prefer-modern-math-apis": "error",
  "unicorn/prefer-module": "error",
  "unicorn/prefer-native-coercion-functions": "error",
  "unicorn/prefer-negative-index": "error",
  "unicorn/prefer-number-properties": "off",
  "unicorn/prefer-object-from-entries": "error",
  "unicorn/prefer-optional-catch-binding": "error",
  "unicorn/prefer-regexp-test": "error",
  "unicorn/prefer-response-static-json": "error",
  "unicorn/prefer-set-has": "error",
  "unicorn/prefer-set-size": "error",
  "unicorn/prefer-spread": "error",
  "unicorn/prefer-string-raw": "error",
  "unicorn/prefer-string-slice": "error",
  "unicorn/prefer-string-trim-start-end": "error",
  "unicorn/prefer-type-error": "error",
  "eslint/arrow-body-style": ["warn", "as-needed"],
  "unicorn/custom-error-definition": "warn",

  "eslint/object-shorthand": ["error", "always"],
  "eslint/no-extra-bind": "error",
  "eslint/no-useless-computed-key": "error",
  "eslint/no-useless-rename": "error",
  "eslint/no-useless-return": "error",
  "eslint/no-eval": [
    "error",
    {
      allowIndirect: false,
    },
  ],
  "eslint/no-prototype-builtins": "error",
  "eslint/eqeqeq": [
    "error",
    "always",
    {
      null: "ignore",
    },
  ],
  "eslint/no-await-in-loop": "error",
  "eslint/no-param-reassign": "error",
  "eslint/array-callback-return": "error",
  "eslint/no-fallthrough": "error",
  "eslint/no-console": [
    "error",
    {
      allow: ["warn", "error"],
    },
  ],
  "eslint/prefer-const": "error",
  "eslint/prefer-arrow-callback": [
    "error",
    {
      allowNamedFunctions: true,
      allowUnboundThis: true,
    },
  ],
  "eslint/prefer-template": "error",
  "eslint/no-var": "error",
  "eslint/no-shadow": "error",
  "typescript/dot-notation": [
    "error",
    {
      allowPattern: "^[A-Za-z_$][\\w$]*_[\\w$]*$",
    },
  ],
  "oxc/no-accumulating-spread": "error",
  "typescript/no-dynamic-delete": "error",
  "typescript/no-empty-object-type": "error",
  "typescript/no-extraneous-class": "error",
  "typescript/no-non-null-asserted-nullish-coalescing": "error",
  "typescript/no-unnecessary-type-constraint": "error",
  "typescript/no-unsafe-function-type": "error",
  "typescript/no-wrapper-object-types": "error",
  "typescript/prefer-literal-enum-member": "error",
  "typescript/prefer-namespace-keyword": "error",
  "typescript/no-for-in-array": "error",
  "typescript/no-implied-eval": "error",
  "typescript/no-unnecessary-boolean-literal-compare": "error",
  "typescript/no-unnecessary-type-arguments": "error",
  "typescript/no-unnecessary-type-parameters": "error",
  "typescript/no-unsafe-unary-minus": "error",
  "typescript/prefer-reduce-type-parameter": "error",
  "typescript/prefer-return-this-type": "error",
  "typescript/strict-boolean-expressions": "error",
  "typescript/unbound-method": "error",
  "typescript/consistent-generic-constructors": "error",
  "typescript/consistent-type-definitions": "error",
  "typescript/non-nullable-type-assertion-style": "error",
  "typescript/prefer-function-type": "error",
} satisfies NonNullable<OxlintConfig["rules"]>);
const OVERRIDES = [
  {
    files: [
      "**/*.{test,spec,e2e}.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
      "**/test/**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
      "**/tests/**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
      "**/__tests__/**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
    ],
    rules: {
      "typescript/consistent-type-assertions": "off",
      "typescript/no-unsafe-assignment": "off",
      "typescript/no-unsafe-type-assertion": "off",
      "typescript/no-unsafe-member-access": "off",
      "typescript/no-non-null-assertion": "off",
      "typescript/promise-function-async": "off",
      "typescript/require-await": "off",
      "eslint/no-await-in-loop": "off",
      "unicorn/consistent-function-scoping": "off",
      "vitest/prefer-called-once": "error",
      "vitest/prefer-expect-resolves": "error",
      "vitest/prefer-to-be": "error",
      "jest/prefer-to-be": "off",
    },
  },
  {
    files: ["**/*.{jsx,tsx}"],
    rules: {
      "typescript/strict-void-return": "off",
    },
  },
  {
    files: ["**/components/ui/**", "**/components/design-system/**"],
    rules: {
      "react/forbid-elements": "off",
      "shadcn/no-restyle": "off",
      "shadcn/no-arbitrary-values": "off",
      "shadcn/require-static-classes": "off",
      "react/button-has-type": "error",
    },
  },
  {
    files: [
      "**/*.{test,spec,e2e}.{js,jsx,ts,tsx}",
      "**/test/**",
      "**/tests/**",
      "**/__tests__/**",
      "**/fixtures/**",
      "**/e2e/**",
      "**/e2e-apps/**",
      "**/perf-regression/**",
      "**/components/ui/**",
      "**/components/design-system/**",
    ],
    rules: {
      "@sarj/prefer-shadcn-primitives": "off",
    },
  },
] as const;

const SKIP_DIRECTORIES: ReadonlySet<string> = new Set([
  "node_modules",
  "dist",
  "build",
  "out",
  "coverage",
  "vendor",
  ".git",
]);
/** Shared native policy. Paths in overrides are relative to the importing config file. */
type TestFramework =
  | "vitest"
  | "bun"
  | "node"
  | "testing-library"
  | "playwright";
interface StrictConfigOptions {
  root: string;
  typeAware?: boolean;
  testFrameworks?: readonly TestFramework[];
  playwrightTestFiles?: readonly string[];
  bunTestFiles?: readonly string[];
  syntaxOnlyConfigFiles?: readonly string[];
  query?: boolean;
  nextjs?: boolean;
  sonarjs?: boolean;
}

export async function createStrictOxlintConfig({
  root,
  typeAware,
  query = false,
  nextjs = false,
  sonarjs = false,
  testFrameworks = ["vitest", "node"],
  playwrightTestFiles = [
    "**/*.{playwright,pw}.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
    "**/playwright/**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
  ],
  syntaxOnlyConfigFiles = [
    "**/vite.config.ts",
    "**/.dependency-cruiser.{js,cjs,mjs,ts,cts,mts}",
  ],
  bunTestFiles = [
    "**/*.bun.{test,spec}.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
    "**/bun/**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
  ],
}: StrictConfigOptions) {
  const useTypeAware = typeAware ?? (await hasTypeProject(path.resolve(root)));
  const frameworks = new Set(testFrameworks);
  validateTestFrameworks(frameworks);
  return defineConfig({
    plugins: [
      "eslint",
      "typescript",
      "unicorn",
      "oxc",
      "react",
      "import",
      "jsdoc",
      "jsx-a11y",
      "nextjs",
      "promise",
      "node",
      "vitest",
      "jest",
    ],
    jsPlugins: [
      { name: "sarj-query", specifier: "@sarj/oxlint-plugin/upstream/query" },
      { name: "sarj-nextjs", specifier: "@sarj/oxlint-plugin/upstream/nextjs" },
      {
        name: "sarj-sonarjs",
        specifier: "@sarj/oxlint-plugin/upstream/sonarjs",
      },
      { name: "@sarj", specifier: "@sarj/oxlint-plugin" },
      {
        name: "sarj-unicorn",
        specifier: "@sarj/oxlint-plugin/upstream/unicorn",
      },
      {
        name: "sarj-typescript",
        specifier: "@sarj/oxlint-plugin/upstream/typescript",
      },
      { name: "sarj-core", specifier: "@sarj/oxlint-plugin/upstream/core" },
      { name: "sarj-jsdoc", specifier: "@sarj/oxlint-plugin/upstream/jsdoc" },
      { name: "zod", specifier: "@sarj/oxlint-plugin/upstream/zod" },
      {
        name: "perfectionist",
        specifier: "@sarj/oxlint-plugin/upstream/perfectionist",
      },
      {
        name: "simple-import-sort",
        specifier: "@sarj/oxlint-plugin/upstream/simple-import-sort",
      },
      {
        name: "node-test",
        specifier: "@sarj/oxlint-plugin/upstream/node-test",
      },
      { name: "sarj-node", specifier: "@sarj/oxlint-plugin/upstream/node" },
      { name: "sarj-bun", specifier: "@sarj/oxlint-plugin/upstream/bun" },
      { name: "sarj-test", specifier: "@sarj/oxlint-plugin/upstream/test" },
      {
        name: "sarj-playwright",
        specifier: "@sarj/oxlint-plugin/upstream/playwright",
      },
      {
        name: "sarj-testing-library",
        specifier: "@sarj/oxlint-plugin/upstream/testing-library",
      },
      { name: "sarj-react", specifier: "@sarj/oxlint-plugin/upstream/react" },
      { name: "sarj-react-hooks", specifier: "@sarj/oxlint-react-hooks" },
      { name: "shadcn", specifier: "@sarj/oxlint-plugin/upstream/shadcn" },
      {
        name: "better-tailwindcss",
        specifier: "@sarj/oxlint-plugin/upstream/better-tailwindcss",
      },
    ].map((plugin) => ({
      ...plugin,
      specifier: fileURLToPath(import.meta.resolve(plugin.specifier)),
    })),
    categories: { correctness: "warn" },
    settings: {
      "testing-library/custom-queries": "off",
      "testing-library/custom-renders": "off",
      "testing-library/utils-module": "off",
    },
    env: { browser: true, node: true, es2024: true },
    globals: Object.fromEntries(
      Object.keys({
        ...globals.builtin,
        ...globals.node,
        ...globals.browser,
      }).map((name) => [name, "readonly" as const]),
    ),
    options: {
      typeAware: useTypeAware,
      reportUnusedDisableDirectives: "error",
      respectEslintDisableDirectives: false,
    },
    ignorePatterns: [
      "**/dist/**",
      "**/build/**",
      "**/out/**",
      "**/esm/**",
      "**/cjs/**",
      "**/umd/**",
      "**/coverage/**",
      "**/.next/**",
      "**/.nuxt/**",
      "**/.output/**",
      "**/.turbo/**",
      "**/.svelte-kit/**",
      "**/.astro/**",
      "**/.wrangler/**",
      "**/.pnp.cjs",
      "**/.pnp.loader.mjs",
      "**/.yarn/releases/**",
      "**/storybook-static/**",
      "**/__generated__/**",
      "**/generated/**",
      "**/*.min.js",
      "**/*.min.mjs",
      "**/*.min.cjs",
    ],
    rules: {
      ...Object.fromEntries(
        Object.keys(RECOMMENDED_RULES).map((name) => [name, "warn" as const]),
      ),
      ...TYPESCRIPT_PRESET_RULES,
      ...NATIVE_RULES,
      ...UPSTREAM_RULES,
      ...strictRules,
      "@sarj/prefer-await-in-async-return": [
        "error",
        { scope: "all-promise-calls" },
      ],
      "eslint/no-new-func": useTypeAware ? "off" : "error",
      "eslint/no-implied-eval": useTypeAware ? "off" : "error",
      "eslint/logical-assignment-operators": [
        "warn",
        "always",
        { enforceForIfStatements: false },
      ],
      "eslint/no-restricted-imports": [
        "error",
        {
          paths: [
            ...LIBRARY_IMPORT_RESTRICTIONS,
            {
              name: "@clerk/nextjs",
              importNames: ["auth", "currentUser"],
              message: "Prefer an internal user-service wrapper.",
            },
            {
              name: "@clerk/nextjs/server",
              message: "Prefer an internal user-service wrapper.",
            },
          ],
          patterns: LIBRARY_IMPORT_RESTRICTIONS.map(({ name, message }) => ({
            group: [`${name}/*`],
            message,
          })),
        },
      ],
    },
    overrides: [
      TYPESCRIPT_COMPATIBILITY_OVERRIDE,
      ...UPSTREAM_OVERRIDES,
      ...OVERRIDES.map((override) => ({
        ...override,
        files: [...override.files],
        rules: { ...override.rules },
      })),
      {
        files: [...OVERRIDES[0].files],
        rules: {
          "vitest/prefer-called-once": frameworks.has("vitest")
            ? "error"
            : "off",
          "vitest/prefer-expect-resolves": frameworks.has("vitest")
            ? "error"
            : "off",
          "vitest/prefer-to-be": frameworks.has("vitest") ? "error" : "off",
          "sarj-bun/prefer-to-be":
            frameworks.has("bun") && !frameworks.has("vitest")
              ? "error"
              : "off",
          "node-test/no-assert-throws-multiple-statements": frameworks.has(
            "node",
          )
            ? "error"
            : "off",
          "node-test/no-assert-throws-async": frameworks.has("node")
            ? "error"
            : "off",
          "node-test/no-unneeded-async-rejects-callback": frameworks.has("node")
            ? "error"
            : "off",
          "node-test/no-useless-assertion": frameworks.has("node")
            ? "error"
            : "off",
          "sarj-testing-library/no-unnecessary-act": frameworks.has(
            "testing-library",
          )
            ? ["error", { isStrict: false }]
            : "off",
          "sarj-testing-library/prefer-screen-queries": frameworks.has(
            "testing-library",
          )
            ? "error"
            : "off",
          "sarj-testing-library/await-async-queries": frameworks.has(
            "testing-library",
          )
            ? "error"
            : "off",
          "sarj-testing-library/await-async-utils": frameworks.has(
            "testing-library",
          )
            ? "error"
            : "off",
          "sarj-testing-library/await-async-events": frameworks.has(
            "testing-library",
          )
            ? "error"
            : "off",
        },
      },
      ...(frameworks.has("bun")
        ? [
            {
              files: [...bunTestFiles],

              rules: {
                "sarj-bun/prefer-to-be": "error" as const,
                "vitest/prefer-to-be": "off" as const,
                "vitest/prefer-called-once": "off" as const,
                "vitest/prefer-expect-resolves": "off" as const,
              },
            },
          ]
        : []),
      ...(frameworks.has("playwright")
        ? [
            {
              files: [...playwrightTestFiles],
              rules: {
                "sarj-playwright/no-unnecessary-assertions": "error" as const,
                "sarj-playwright/missing-playwright-await": "error" as const,
                "sarj-bun/prefer-to-be": "off" as const,
                "jest/prefer-to-be": "off" as const,
                "vitest/prefer-to-be": "off" as const,
                "vitest/prefer-called-once": "off" as const,
                "vitest/prefer-expect-resolves": "off" as const,
              },
            },
          ]
        : []),
      {
        files: ["**/*.{ts,tsx}"],
        rules: Object.fromEntries(
          Object.entries(TANSTACK_QUERY_RECOMMENDED_RULES).map(
            ([name, level]) => [name, query ? level : "off"],
          ),
        ),
      },
      ...syntaxOnlyOverrides(syntaxOnlyConfigFiles),
      {
        files: ["**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}"],
        rules: Object.fromEntries(
          Object.entries(SONARJS_ADDITIONAL_RULES).map(([name, level]) => [
            name,
            sonarjs ? level : "off",
          ]),
        ),
      },
      {
        files: ["**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}"],
        rules: Object.fromEntries(
          Object.entries(NEXTJS_ADDITIONAL_RECOMMENDED_RULES).map(
            ([name, level]) => [name, nextjs ? level : "off"],
          ),
        ),
      },
    ],
  });
}

function validateTestFrameworks(frameworks: ReadonlySet<string>) {
  for (const framework of frameworks) {
    if (
      !["vitest", "bun", "node", "testing-library", "playwright"].includes(
        framework,
      )
    ) {
      throw new Error(
        `Unsupported test framework ${JSON.stringify(framework)}`,
      );
    }
  }
}

function syntaxOnlyOverrides(files: readonly string[]) {
  if (!files.length) return [];
  const namingConvention = [
    "error",
    ...UPSTREAM_RULES["sarj-typescript/naming-convention"]
      .slice(1)
      .filter((option) => typeof option !== "object" || !("types" in option)),
  ] satisfies NonNullable<OxlintConfig["rules"]>[string];
  return [
    {
      files: [...files],
      rules: {
        ...Object.fromEntries(
          TYPE_AWARE_RULE_IDS.map((name) => [name, "off" as const]),
        ),
        "eslint/no-new-func": "error" as const,
        "eslint/no-implied-eval": "error" as const,
        "sarj-typescript/naming-convention": namingConvention,
      },
    },
  ];
}

async function hasTypeProject(root: string): Promise<boolean> {
  const pending = [{ directory: root, depth: 0 }];
  let visited = 0;
  while (pending.length > 0 && visited < 2000) {
    const entry = pending.pop()!;
    visited += 1;
    let children;
    try {
      children = await readdir(entry.directory, { withFileTypes: true });
    } catch {
      continue;
    }
    if (
      children.some(
        (child) =>
          child.isFile() &&
          ["tsconfig.json", "jsconfig.json"].includes(child.name),
      )
    )
      return true;
    if (entry.depth >= 8) continue;
    for (const child of children) {
      if (
        child.isDirectory() &&
        !child.name.startsWith(".") &&
        !SKIP_DIRECTORIES.has(child.name)
      ) {
        pending.push({
          directory: path.join(entry.directory, child.name),
          depth: entry.depth + 1,
        });
      }
    }
  }
  return false;
}
