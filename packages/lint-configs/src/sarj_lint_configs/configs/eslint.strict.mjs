import tseslint from "typescript-eslint";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import unicorn from "eslint-plugin-unicorn";
import eslintComments from "@eslint-community/eslint-plugin-eslint-comments";
import zod from "eslint-plugin-zod";
import perfectionist from "eslint-plugin-perfectionist";
import simpleImportSort from "eslint-plugin-simple-import-sort";
import betterTailwindcss from "eslint-plugin-better-tailwindcss";
import sarj from "@sarj/eslint-plugin";


/** @type {import("eslint").Linter.Config[]} */
const config = [
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,

  {
    // Dead eslint-disable directives are an error (parity with ruff RUF100).
    linterOptions: {
      reportUnusedDisableDirectives: "error",
    },
    plugins: {
      "@typescript-eslint": tseslint.plugin,
      react,
      "react-hooks": reactHooks,
      unicorn,
      "@eslint-community/eslint-comments": eslintComments,
      zod,
      perfectionist,
      "simple-import-sort": simpleImportSort,
      "@sarj": sarj,
    },
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: process.cwd(),
        ecmaFeatures: { jsx: true },
      },
    },
    settings: { react: { version: "detect" } },
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-non-null-assertion": "error",
      "@typescript-eslint/no-deprecated": "error",
      "@typescript-eslint/only-throw-error": "error",
      "@typescript-eslint/prefer-promise-reject-errors": "error",
      "@typescript-eslint/no-meaningless-void-operator": "error",
      "@typescript-eslint/no-mixed-enums": "error",
      "@typescript-eslint/prefer-find": "error",
      "@typescript-eslint/prefer-readonly": "error",
      "@typescript-eslint/no-unsafe-assignment": "error",
      "@typescript-eslint/no-unsafe-member-access": "error",
      "@typescript-eslint/no-unsafe-argument": "error",
      "@typescript-eslint/no-unsafe-call": "error",
      "@typescript-eslint/no-unsafe-return": "error",
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/await-thenable": "error",
      "@typescript-eslint/no-misused-promises": "error",
      "@typescript-eslint/require-await": "error",
      "@typescript-eslint/restrict-template-expressions": "error",
      "@typescript-eslint/no-unused-vars": ["error", {
        argsIgnorePattern: "^_",
        varsIgnorePattern: "^_",
        caughtErrorsIgnorePattern: "^_",
        ignoreRestSiblings: true,
      }],
      "@typescript-eslint/consistent-indexed-object-style": ["error", "record"],
      "@typescript-eslint/consistent-type-imports": ["error", {
        prefer: "type-imports",
        fixStyle: "inline-type-imports",
      }],
      "@typescript-eslint/switch-exhaustiveness-check": "error",
      "@typescript-eslint/consistent-type-assertions": ["error", {
        assertionStyle: "never",
        objectLiteralTypeAssertions: "never",
      }],
      "@typescript-eslint/naming-convention": [
        "error",
        { selector: "default", format: ["camelCase"], leadingUnderscore: "allow" },
        { selector: "variable", format: ["camelCase", "UPPER_CASE", "PascalCase"], leadingUnderscore: "allow" },
        { selector: "typeLike", format: ["PascalCase"] },
        { selector: "import", format: ["camelCase", "PascalCase", "UPPER_CASE"] },
        { selector: "objectLiteralProperty", format: null },
        { selector: "typeProperty", format: null },
        { selector: "parameter", format: ["camelCase", "snake_case"], leadingUnderscore: "allow" },
      ],

      // Additional type-aware strictness incorporated from bulbul's base config.
      "@typescript-eslint/prefer-as-const": "error",
      "@typescript-eslint/no-unnecessary-condition": "error",
      "@typescript-eslint/prefer-nullish-coalescing": "error",
      "@typescript-eslint/prefer-optional-chain": "error",
      "@typescript-eslint/promise-function-async": "error",
      "@typescript-eslint/no-non-null-asserted-optional-chain": "error",
      "@typescript-eslint/no-unnecessary-type-assertion": "error",
      "@typescript-eslint/no-redundant-type-constituents": "error",
      "@typescript-eslint/require-array-sort-compare": "error",
      "@typescript-eslint/no-unsafe-type-assertion": "error",
      "@typescript-eslint/no-unsafe-enum-comparison": "error",
      "@typescript-eslint/no-base-to-string": "error",
      "@typescript-eslint/no-misused-spread": "error",
      "@typescript-eslint/no-unnecessary-type-conversion": "error",
      "@typescript-eslint/prefer-includes": "error",
      "@typescript-eslint/prefer-string-starts-ends-with": "error",
      "@typescript-eslint/no-confusing-non-null-assertion": "error",
      "@typescript-eslint/no-duplicate-type-constituents": "error",
      "@typescript-eslint/no-invalid-void-type": "error",
      "@typescript-eslint/no-unnecessary-template-expression": "error",
      "@typescript-eslint/no-import-type-side-effects": "error",
      "@typescript-eslint/array-type": "error",
      "no-else-return": "error",

      "react/jsx-no-leaked-render": ["error", { validStrategies: ["ternary", "coerce"] }],
      "react/no-unstable-nested-components": ["error", { prohibitLocalVariables: true }],
      "react-hooks/exhaustive-deps": "error",
      "react-hooks/rules-of-hooks": "error",
      "react/forbid-elements": ["error", { forbid: [
        { element: "button",   message: "Use <Button> from your design system." },
        { element: "input",    message: "Use <Input> / <Checkbox> / <RadioGroup> from your design system." },
        { element: "select",   message: "Use <Select> from your design system." },
        { element: "textarea", message: "Use <Textarea> from your design system." },
        { element: "dialog",   message: "Use <Dialog> / <AlertDialog> from your design system." },
        { element: "table",    message: "Use <Table> family from your design system." },
      ]}],
      "react/forbid-component-props": ["error", { forbid: [
        { propName: "style", message: "Use design-token utility classes. For dynamic values, set a CSS custom property and reference it via an arbitrary-value class." },
      ]}],
      "react/forbid-dom-props": ["error", { forbid: [
        { propName: "style", message: "Use design-token utility classes. For dynamic values, set a CSS custom property and reference it via an arbitrary-value class." },
      ]}],
      "react/jsx-pascal-case": "error",
      "react/no-danger": "error",
      "react/no-this-in-sfc": "error",
      "react/jsx-no-comment-textnodes": "error",
      "react/jsx-no-duplicate-props": "error",
      "react/jsx-no-target-blank": "error",
      "react/jsx-no-undef": "error",
      "react/void-dom-elements-no-children": "error",
      "react/jsx-fragments": "error",
      "react/jsx-no-script-url": "error",
      "react/self-closing-comp": "error",
      "react/jsx-no-useless-fragment": "error",
      "react/jsx-boolean-value": ["error", "never"],

      "unicorn/consistent-function-scoping": "error",
      "unicorn/filename-case": ["error", { cases: { kebabCase: true }, ignore: [String.raw`\.d\.ts$`] }],
      "unicorn/prefer-switch": "warn",
      "unicorn/no-array-for-each": "warn",
      "unicorn/no-useless-undefined": "error",
      "unicorn/prefer-node-protocol": "error",
      "unicorn/prefer-string-replace-all": "error",
      "unicorn/prefer-top-level-await": "error",
      "unicorn/no-await-expression-member": "error",
      "unicorn/prefer-structured-clone": "error",
      "unicorn/prefer-logical-operator-over-ternary": "error",
      "unicorn/relative-url-style": ["error", "never"],
      "unicorn/throw-new-error": "error",

      "zod/prefer-enum-over-literal-union": "error",

      // Deterministic ordering (incorporated from bulbul). perfectionist sorts
      // structural members; simple-import-sort owns import/export ordering
      // (chosen over eslint-plugin-import to avoid Next.js resolver conflicts).
      "perfectionist/sort-objects": ["error", { type: "natural", order: "asc" }],
      "perfectionist/sort-interfaces": "error",
      "perfectionist/sort-classes": "error",
      "perfectionist/sort-jsx-props": "error",
      "perfectionist/sort-union-types": "error",
      "simple-import-sort/imports": "error",
      "simple-import-sort/exports": "error",

      // Every suppression must say WHY. `require-description` already covers
      // eslint-disable comments and `@typescript-eslint/ban-ts-comment` (from
      // strictTypeChecked) covers `@ts-expect-error`, so a bespoke rule would be
      // a duplicate.
      "@eslint-community/eslint-comments/require-description": ["error", { ignore: [] }],
      // ...and a suppression must name the rule it suppresses. A bare
      // `/* eslint-disable */` at the top of a file silently switches off EVERY
      // rule for the whole file — including ones added later — which is the
      // file-level-suppression escape hatch flagged repeatedly in review.
      "@eslint-community/eslint-comments/no-unlimited-disable": "error",
      "@eslint-community/eslint-comments/no-restricted-disable": ["warn",
        "no-console",
        "react-hooks/exhaustive-deps",
      ],

      // Dedup: TS-enum ban → @sarj/no-enum, oversized-try-block ban →
      // @sarj/no-fat-try-blocks, and process.env ban → @sarj/no-raw-env (all
      // added below). Only the selectors WITHOUT a @sarj equivalent stay here,
      // so each concern fires exactly one diagnostic.
      "no-restricted-syntax": [
        "error",
        {
          selector: "TSModuleDeclaration[kind='namespace']",
          message: "Use ES modules instead of namespaces.",
        },
        {
          selector: "CallExpression[callee.name='useCallback']",
          message: "Don't memoize by hand — the React Compiler handles it. Remove useCallback.",
        },
        {
          selector: "CallExpression[callee.name='useMemo']",
          message: "Don't memoize by hand — the React Compiler handles it. Remove useMemo (extract a plain function or compute inline).",
        },
      ],
      "no-restricted-imports": ["error", {
        paths: [
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
        patterns: ["*/index", "*/index.ts"],
      }],

      "object-shorthand": ["error", "always"],
      "no-return-await": "error",
      eqeqeq: ["error", "always"],
      "no-await-in-loop": "error",
      "no-param-reassign": "error",
      "array-callback-return": "error",
      "no-fallthrough": "error",
      "no-console": ["error", { allow: ["warn", "error"] }],
      "prefer-const": "error",
      "prefer-template": "error",
      "no-var": "error",
      "no-shadow": "off",
      "@typescript-eslint/no-shadow": "error",

      // Full @sarj/eslint-plugin@2.7.0 strict ruleset. Tiers mirror the plugin's
      // own `configs.strict` — error for most, warn for the stylistic/high-volume
      // rules (prefer-semantic-colors, prefer-string-literal-union,
      // no-unsafe-cast) — with one deliberate deviation: enforce-file-structure
      // is warn here while the plugin's own strict has it at error (structural
      // moves are high-churn for existing consumers, so it stays advisory).
      // no-enum / no-fat-try-blocks / no-raw-env are the single owners of the
      // enum / oversized-try / process.env concerns (the native no-restricted-*
      // equivalents were removed above).
      "@sarj/zod-naming-convention": "error",
      "@sarj/require-assert-never": "error",
      "@sarj/require-zod-form-validation": "error",
      "@sarj/prefer-schema-for-api-payload": "error",
      "@sarj/no-client-side-data-fetching": "error",
      "@sarj/prefer-server-actions": "error",
      "@sarj/no-unnecessary-use-client": "error",
      "@sarj/no-enum": "error",
      "@sarj/no-raw-env": "error",
      "@sarj/prefer-shadcn": "error",
      "@sarj/no-sequential-await": "error",
      "@sarj/no-sentinel-return-on-catch": "error",
      "@sarj/no-log-only-catch": "error",
      "@sarj/no-insecure-random-id": "error",
      "@sarj/no-json-stringify-error": "error",
      "@sarj/no-string-concat-in-loop": "error",
      "@sarj/prefer-discriminated-union": "error",
      "@sarj/no-comment-cruft": "error",
      "@sarj/no-fat-try-blocks": "error",
      "@sarj/no-cors-wildcard-with-credentials": "error",
      "@sarj/no-secret-in-log": "error",
      "@sarj/single-public-export": "error",
      // Mined from 2y of PR review feedback + 5-repo code-smell audit (2026-07).
      "@sarj/require-fetch-timeout": "error",
      "@sarj/no-silent-promise-catch": "error",
      "@sarj/require-schema-validate-search": "error",
      "@sarj/enforce-file-structure": "warn",
      "@sarj/prefer-semantic-colors": "warn",
      "@sarj/prefer-string-literal-union": "warn",
      // High-volume/stylistic — warn until rollout proves FP rate.
      "@sarj/no-unsafe-cast": "warn",
    },
  },

  {
    files: ["**/*.test.ts", "**/*.test.tsx", "**/__tests__/**/*"],
    rules: {
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
    },
  },

  {
    files: ["**/components/ui/**", "**/components/design-system/**"],
    rules: {
      "react/forbid-elements": "off",
    },
  },

  {
    // The env source-of-truth files parse process.env into a Zod-validated
    // object the rest of the app imports; they're the one place raw env access
    // is legitimate, so @sarj/no-raw-env (which replaced the native
    // no-restricted-properties process.env ban) is disabled here.
    files: [
      "**/*.config.{ts,tsx,js,jsx,mjs,cjs,mts,cts}",
      "**/scripts/**",
      "**/env/**",
      "**/env.{ts,tsx,js,mjs}",
      "**/server-env.{ts,tsx,js,mjs}",
      "**/client-env.{ts,tsx,js,mjs}",
      "**/server-settings.{ts,tsx,js,mjs}",
      "**/client-settings.{ts,tsx,js,mjs}",
    ],
    rules: {
      "@sarj/no-raw-env": "off",
    },
  },

  // better-tailwindcss: class-string hygiene for Tailwind repos. Scoped to JSX/TSX
  // (where className strings live) and harmless where no Tailwind classes exist —
  // these three rules only inspect literal class strings, so non-Tailwind repos
  // simply see zero findings. Kept in its own block so the plugin is only wired
  // where it applies.
  {
    files: ["**/*.{jsx,tsx}"],
    plugins: {
      "better-tailwindcss": betterTailwindcss,
    },
    rules: {
      "better-tailwindcss/no-conflicting-classes": "error",
      "better-tailwindcss/no-duplicate-classes": "error",
      "better-tailwindcss/no-deprecated-classes": "error",
    },
  },
];

export default config;
