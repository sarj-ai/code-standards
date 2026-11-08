import { defineConfig, type OxlintConfig, type OxlintOverride } from "oxlint";

// The managed Oxlint policy: every rule the ESLint-era eslint.strict.ts enabled,
// as the native Oxlint rule where one exists and otherwise as the rule from its
// ESLint plugin, loaded under `jsPlugins`. oxlint.rule-map.json records where
// each ESLint rule went (native, JS plugin alias, replaced or dropped) and why.
// Type-aware rules and the type check run through tsrs (`tsrs-lint`).
//
// A repository extends this from its own oxlint.config.mts:
//
//   import { defineConfig } from "oxlint";
//   import { createConfig, ignorePatterns } from "./oxlint.strict.mts";
//
//   export default defineConfig({
//     extends: [createConfig()],
//     ignorePatterns: [...ignorePatterns],
//     overrides: [],
//   });
//
// Oxlint reads `ignorePatterns` only from the root config, never from an
// extended one, so the repository config spreads them itself. Both files are
// `.mts` so Node loads them as modules without `"type": "module"`.
//
// Native plugin names are reserved, so ESLint plugins that share one load
// under an alias (`eslint-js`, `unicorn-js`, `jsdoc-js`, `react-js`), and a
// disable comment names the alias.

const TEST_FRAMEWORKS = ["vitest", "bun", "node", "testing-library", "playwright"] as const;
export type TestFramework = (typeof TEST_FRAMEWORKS)[number];

export interface ConfigOptions {
  /** Files linted without type-aware rules. Pass [] when the project type-checks its tool configs. */
  readonly syntaxOnlyConfigFiles?: readonly string[];
  /** Test runners in use. Vitest is the default Sarj runner; others are explicit. */
  readonly testFrameworks?: readonly TestFramework[];
  readonly playwrightTestFiles?: readonly string[];
  readonly bunTestFiles?: readonly string[];
}

const JS_FILES = ["**/*.{js,jsx,mjs,cjs}"];
const JSX_FILES = ["**/*.{jsx,tsx}"];
const TEST_FILES = [
  "**/*.{test,spec,e2e}.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
  "**/test/**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
  "**/tests/**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
  "**/__tests__/**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
];
const DEFAULT_PLAYWRIGHT_TEST_FILES = [
  "**/*.{playwright,pw}.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
  "**/playwright/**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
];
const DEFAULT_BUN_TEST_FILES = [
  "**/*.bun.{test,spec}.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
  "**/bun/**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
];
const DEFAULT_SYNTAX_ONLY_CONFIG_FILES = [
  "**/vite.config.ts",
  "**/.dependency-cruiser.{js,cjs,mjs,ts,cts,mts}",
  "**/eslint.config*.{js,cjs,mjs,ts,cts,mts}",
];
// Shadcn primitives may be restyled inside the component library, and tests
// and fixtures render raw elements on purpose.
const SHADCN_EXEMPT_FILES = [
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
];
// Barrel files defeat Next.js's per-route bundling.
const NEXT_APP_FILES = ["**/app/**", "**/pages/**"];

/**
 * Build output, generated code and lint configs. `lib/` often holds authored
 * code, so a package that emits into it ignores that folder itself.
 */
export const ignorePatterns: readonly string[] = [
  "**/node_modules/**",
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
  "**/*.min.{js,mjs,cjs}",
  // Lint configs were never linted under ESLint either.
  "**/eslint.config.{js,cjs,mjs,ts,mts,cts}",
  "**/eslint.strict.{mjs,ts}",
  "**/oxlint.{config,strict}.{ts,mts}",
  "**/oxfmt.{config,strict}.{ts,mts}",
  "**/syncpack.strict.mts",
];

// BEGIN GENERATED LIBRARY POLICY
const LIBRARY_IMPORT_PATHS = [
  {"message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch.", "name": "request"},
  {"message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch.", "name": "node-fetch"},
  {"message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch.", "name": "cross-fetch"},
  {"message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch.", "name": "isomorphic-fetch"},
  {"message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch.", "name": "axios"},
  {"message": "LIB102: Standards standardizes date utilities on date-fns; migration is not API-compatible. Replace with date-fns.", "name": "moment"},
  {"message": "LIB102: Standards standardizes date utilities on date-fns; migration is not API-compatible. Replace with date-fns.", "name": "dayjs"},
  {"message": "LIB103: Standards standardizes collection utilities on Remeda and native APIs. Replace with remeda.", "name": "lodash"},
  {"message": "LIB103: Standards standardizes collection utilities on Remeda and native APIs. Replace with remeda.", "name": "lodash-es"},
  {"message": "LIB103: Standards standardizes collection utilities on Remeda and native APIs. Replace with remeda.", "name": "underscore"},
  {"message": "LIB104: Use clsx for conditional class-name composition. Replace with clsx.", "name": "classnames"},
  {"message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod.", "name": "joi"},
  {"message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod.", "name": "yup"},
  {"message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod.", "name": "superstruct"},
  {"message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod.", "name": "io-ts"},
  {"message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod.", "name": "runtypes"},
  {"message": "LIB106: Use jose; review key formats and async signing and verification APIs. Replace with jose.", "name": "jsonwebtoken"},
  {"message": "LIB107: Standards standardizes servers on Hono; Node deployments also need @hono/node-server. Replace with hono.", "name": "express"},
  {"message": "LIB107: Standards standardizes servers on Hono; Node deployments also need @hono/node-server. Replace with hono.", "name": "koa"},
  {"message": "LIB108: Standards standardizes tests on Vitest; review globals, timers, mocks, and environment setup. Replace with vitest.", "name": "jest"},
  {"message": "LIB108: Standards standardizes tests on Vitest; review globals, timers, mocks, and environment setup. Replace with vitest.", "name": "mocha"},
  {"message": "LIB109: Use Vitest spies, mocks, and fake timers instead of Sinon. Replace with Vitest mocks.", "name": "sinon"},
  {"message": "LIB110: Standards standardizes command-line interfaces on citty. Replace with citty.", "name": "commander"},
  {"message": "LIB110: Standards standardizes command-line interfaces on citty. Replace with citty.", "name": "yargs"},
  {"message": "LIB111: Use native Promise, adding p-limit or p-map only for the extensions actually needed. Replace with native Promise.", "name": "bluebird"},
  {"message": "LIB112: Prefer node:fs/promises; verify recursive removal, copy, path, and error semantics. Replace with node:fs/promises.", "name": "rimraf"},
  {"message": "LIB112: Prefer node:fs/promises; verify recursive removal, copy, path, and error semantics. Replace with node:fs/promises.", "name": "fs-extra"},
  {"message": "LIB113: Node 22 provides global AbortController. Replace with AbortController.", "name": "abort-controller"},
  {"message": "LIB114: Use URLSearchParams and explicitly review repeated keys, escaping, arrays, and object coercion. Replace with URLSearchParams.", "name": "querystring"},
  {"message": "LIB115: Standards standardizes environment loading on @dotenvx/dotenvx. Replace with @dotenvx/dotenvx.", "name": "dotenv"},
  {"message": "LIB116: Use picocolors for terminal colors. Replace with picocolors.", "name": "chalk"},
  {"message": "LIB117: The original faker package is abandoned; use @faker-js/faker. Replace with @faker-js/faker.", "name": "faker"},
  {"message": "LIB118: node-sass is end-of-life; use Dart Sass. Replace with sass.", "name": "node-sass"},
  {"message": "LIB119: TSLint is deprecated; use ESLint with typescript-eslint. Replace with eslint.", "name": "tslint"},
  {"message": "LIB120: Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata. Replace with direct object-storage uploads with signed URLs.", "name": "multer"},
  {"message": "LIB120: Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata. Replace with direct object-storage uploads with signed URLs.", "name": "formidable"},
  {"message": "LIB120: Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata. Replace with direct object-storage uploads with signed URLs.", "name": "busboy"},
  {"message": "LIB120: Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata. Replace with direct object-storage uploads with signed URLs.", "name": "@fastify/multipart"},
  {"message": "LIB120: Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata. Replace with direct object-storage uploads with signed URLs.", "name": "express-fileupload"},
  {"message": "LIB120: Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata. Replace with direct object-storage uploads with signed URLs.", "name": "multiparty"},
];
const LIBRARY_IMPORT_PATTERNS = [
  {"group": ["request/*"], "message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch."},
  {"group": ["node-fetch/*"], "message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch."},
  {"group": ["cross-fetch/*"], "message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch."},
  {"group": ["isomorphic-fetch/*"], "message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch."},
  {"group": ["axios/*"], "message": "LIB101: Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration. Replace with native fetch."},
  {"group": ["moment/*"], "message": "LIB102: Standards standardizes date utilities on date-fns; migration is not API-compatible. Replace with date-fns."},
  {"group": ["dayjs/*"], "message": "LIB102: Standards standardizes date utilities on date-fns; migration is not API-compatible. Replace with date-fns."},
  {"group": ["lodash/*"], "message": "LIB103: Standards standardizes collection utilities on Remeda and native APIs. Replace with remeda."},
  {"group": ["lodash-es/*"], "message": "LIB103: Standards standardizes collection utilities on Remeda and native APIs. Replace with remeda."},
  {"group": ["underscore/*"], "message": "LIB103: Standards standardizes collection utilities on Remeda and native APIs. Replace with remeda."},
  {"group": ["classnames/*"], "message": "LIB104: Use clsx for conditional class-name composition. Replace with clsx."},
  {"group": ["joi/*"], "message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod."},
  {"group": ["yup/*"], "message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod."},
  {"group": ["superstruct/*"], "message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod."},
  {"group": ["io-ts/*"], "message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod."},
  {"group": ["runtypes/*"], "message": "LIB105: Standards standardizes runtime validation on Zod; schemas are not drop-in compatible. Replace with zod."},
  {"group": ["jsonwebtoken/*"], "message": "LIB106: Use jose; review key formats and async signing and verification APIs. Replace with jose."},
  {"group": ["express/*"], "message": "LIB107: Standards standardizes servers on Hono; Node deployments also need @hono/node-server. Replace with hono."},
  {"group": ["koa/*"], "message": "LIB107: Standards standardizes servers on Hono; Node deployments also need @hono/node-server. Replace with hono."},
  {"group": ["jest/*"], "message": "LIB108: Standards standardizes tests on Vitest; review globals, timers, mocks, and environment setup. Replace with vitest."},
  {"group": ["mocha/*"], "message": "LIB108: Standards standardizes tests on Vitest; review globals, timers, mocks, and environment setup. Replace with vitest."},
  {"group": ["sinon/*"], "message": "LIB109: Use Vitest spies, mocks, and fake timers instead of Sinon. Replace with Vitest mocks."},
  {"group": ["commander/*"], "message": "LIB110: Standards standardizes command-line interfaces on citty. Replace with citty."},
  {"group": ["yargs/*"], "message": "LIB110: Standards standardizes command-line interfaces on citty. Replace with citty."},
  {"group": ["bluebird/*"], "message": "LIB111: Use native Promise, adding p-limit or p-map only for the extensions actually needed. Replace with native Promise."},
  {"group": ["rimraf/*"], "message": "LIB112: Prefer node:fs/promises; verify recursive removal, copy, path, and error semantics. Replace with node:fs/promises."},
  {"group": ["fs-extra/*"], "message": "LIB112: Prefer node:fs/promises; verify recursive removal, copy, path, and error semantics. Replace with node:fs/promises."},
  {"group": ["abort-controller/*"], "message": "LIB113: Node 22 provides global AbortController. Replace with AbortController."},
  {"group": ["querystring/*"], "message": "LIB114: Use URLSearchParams and explicitly review repeated keys, escaping, arrays, and object coercion. Replace with URLSearchParams."},
  {"group": ["dotenv/*"], "message": "LIB115: Standards standardizes environment loading on @dotenvx/dotenvx. Replace with @dotenvx/dotenvx."},
  {"group": ["chalk/*"], "message": "LIB116: Use picocolors for terminal colors. Replace with picocolors."},
  {"group": ["faker/*"], "message": "LIB117: The original faker package is abandoned; use @faker-js/faker. Replace with @faker-js/faker."},
  {"group": ["node-sass/*"], "message": "LIB118: node-sass is end-of-life; use Dart Sass. Replace with sass."},
  {"group": ["tslint/*"], "message": "LIB119: TSLint is deprecated; use ESLint with typescript-eslint. Replace with eslint."},
  {"group": ["multer/*"], "message": "LIB120: Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata. Replace with direct object-storage uploads with signed URLs."},
  {"group": ["formidable/*"], "message": "LIB120: Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata. Replace with direct object-storage uploads with signed URLs."},
  {"group": ["busboy/*"], "message": "LIB120: Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata. Replace with direct object-storage uploads with signed URLs."},
  {"group": ["@fastify/multipart/*"], "message": "LIB120: Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata. Replace with direct object-storage uploads with signed URLs."},
  {"group": ["express-fileupload/*"], "message": "LIB120: Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata. Replace with direct object-storage uploads with signed URLs."},
  {"group": ["multiparty/*"], "message": "LIB120: Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata. Replace with direct object-storage uploads with signed URLs."},
];
const LIBRARY_LOADS = [
  {"id": "LIB101", "module": "request", "note": "Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration.", "replacement": "native fetch"},
  {"id": "LIB101", "module": "node-fetch", "note": "Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration.", "replacement": "native fetch"},
  {"id": "LIB101", "module": "cross-fetch", "note": "Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration.", "replacement": "native fetch"},
  {"id": "LIB101", "module": "isomorphic-fetch", "note": "Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration.", "replacement": "native fetch"},
  {"id": "LIB101", "module": "axios", "note": "Use the platform-native fetch API; review errors, timeouts, retries, and response parsing during migration.", "replacement": "native fetch"},
  {"id": "LIB102", "module": "moment", "note": "Standards standardizes date utilities on date-fns; migration is not API-compatible.", "replacement": "date-fns"},
  {"id": "LIB102", "module": "dayjs", "note": "Standards standardizes date utilities on date-fns; migration is not API-compatible.", "replacement": "date-fns"},
  {"id": "LIB103", "module": "lodash", "note": "Standards standardizes collection utilities on Remeda and native APIs.", "replacement": "remeda"},
  {"id": "LIB103", "module": "lodash-es", "note": "Standards standardizes collection utilities on Remeda and native APIs.", "replacement": "remeda"},
  {"id": "LIB103", "module": "underscore", "note": "Standards standardizes collection utilities on Remeda and native APIs.", "replacement": "remeda"},
  {"id": "LIB104", "module": "classnames", "note": "Use clsx for conditional class-name composition.", "replacement": "clsx"},
  {"id": "LIB105", "module": "joi", "note": "Standards standardizes runtime validation on Zod; schemas are not drop-in compatible.", "replacement": "zod"},
  {"id": "LIB105", "module": "yup", "note": "Standards standardizes runtime validation on Zod; schemas are not drop-in compatible.", "replacement": "zod"},
  {"id": "LIB105", "module": "superstruct", "note": "Standards standardizes runtime validation on Zod; schemas are not drop-in compatible.", "replacement": "zod"},
  {"id": "LIB105", "module": "io-ts", "note": "Standards standardizes runtime validation on Zod; schemas are not drop-in compatible.", "replacement": "zod"},
  {"id": "LIB105", "module": "runtypes", "note": "Standards standardizes runtime validation on Zod; schemas are not drop-in compatible.", "replacement": "zod"},
  {"id": "LIB106", "module": "jsonwebtoken", "note": "Use jose; review key formats and async signing and verification APIs.", "replacement": "jose"},
  {"id": "LIB107", "module": "express", "note": "Standards standardizes servers on Hono; Node deployments also need @hono/node-server.", "replacement": "hono"},
  {"id": "LIB107", "module": "koa", "note": "Standards standardizes servers on Hono; Node deployments also need @hono/node-server.", "replacement": "hono"},
  {"id": "LIB108", "module": "jest", "note": "Standards standardizes tests on Vitest; review globals, timers, mocks, and environment setup.", "replacement": "vitest"},
  {"id": "LIB108", "module": "mocha", "note": "Standards standardizes tests on Vitest; review globals, timers, mocks, and environment setup.", "replacement": "vitest"},
  {"id": "LIB109", "module": "sinon", "note": "Use Vitest spies, mocks, and fake timers instead of Sinon.", "replacement": "Vitest mocks"},
  {"id": "LIB110", "module": "commander", "note": "Standards standardizes command-line interfaces on citty.", "replacement": "citty"},
  {"id": "LIB110", "module": "yargs", "note": "Standards standardizes command-line interfaces on citty.", "replacement": "citty"},
  {"id": "LIB111", "module": "bluebird", "note": "Use native Promise, adding p-limit or p-map only for the extensions actually needed.", "replacement": "native Promise"},
  {"id": "LIB112", "module": "rimraf", "note": "Prefer node:fs/promises; verify recursive removal, copy, path, and error semantics.", "replacement": "node:fs/promises"},
  {"id": "LIB112", "module": "fs-extra", "note": "Prefer node:fs/promises; verify recursive removal, copy, path, and error semantics.", "replacement": "node:fs/promises"},
  {"id": "LIB113", "module": "abort-controller", "note": "Node 22 provides global AbortController.", "replacement": "AbortController"},
  {"id": "LIB114", "module": "querystring", "note": "Use URLSearchParams and explicitly review repeated keys, escaping, arrays, and object coercion.", "replacement": "URLSearchParams"},
  {"id": "LIB115", "module": "dotenv", "note": "Standards standardizes environment loading on @dotenvx/dotenvx.", "replacement": "@dotenvx/dotenvx"},
  {"id": "LIB116", "module": "chalk", "note": "Use picocolors for terminal colors.", "replacement": "picocolors"},
  {"id": "LIB117", "module": "faker", "note": "The original faker package is abandoned; use @faker-js/faker.", "replacement": "@faker-js/faker"},
  {"id": "LIB118", "module": "node-sass", "note": "node-sass is end-of-life; use Dart Sass.", "replacement": "sass"},
  {"id": "LIB119", "module": "tslint", "note": "TSLint is deprecated; use ESLint with typescript-eslint.", "replacement": "eslint"},
  {"id": "LIB120", "module": "multer", "note": "Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata.", "replacement": "direct object-storage uploads with signed URLs"},
  {"id": "LIB120", "module": "formidable", "note": "Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata.", "replacement": "direct object-storage uploads with signed URLs"},
  {"id": "LIB120", "module": "busboy", "note": "Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata.", "replacement": "direct object-storage uploads with signed URLs"},
  {"id": "LIB120", "module": "@fastify/multipart", "note": "Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata.", "replacement": "direct object-storage uploads with signed URLs"},
  {"id": "LIB120", "module": "express-fileupload", "note": "Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata.", "replacement": "direct object-storage uploads with signed URLs"},
  {"id": "LIB120", "module": "multiparty", "note": "Keep upload bytes off application servers; issue a short-lived signed URL and accept object metadata.", "replacement": "direct object-storage uploads with signed URLs"},
];
// END GENERATED LIBRARY POLICY

const RULES = {
  // ESLint core (native).
  "array-callback-return": ["error", {"allowImplicit": false, "checkForEach": false, "allowVoid": false}],
  "arrow-body-style": ["warn", "as-needed"],
  "default-param-last": "error",
  "eqeqeq": ["error", "always", {"null": "ignore"}],
  "for-direction": "warn",
  "logical-assignment-operators": ["warn", "always", {"enforceForIfStatements": false}],
  "no-array-constructor": "error",
  "no-async-promise-executor": "error",
  "no-await-in-loop": "error",
  "no-case-declarations": "warn",
  "no-compare-neg-zero": "warn",
  "no-cond-assign": ["warn", "except-parens"],
  "no-console": ["error", {"allow": ["warn", "error"]}],
  "no-constant-binary-expression": ["error", {"checkRelationalComparisons": false}],
  "no-constant-condition": ["warn", {"checkLoops": "allExceptWhileTrue"}],
  "no-constructor-return": "warn",
  "no-control-regex": "warn",
  "no-debugger": "warn",
  "no-delete-var": "warn",
  "no-dupe-else-if": "warn",
  "no-duplicate-case": "warn",
  "no-empty": ["warn", {"allowEmptyCatch": false}],
  "no-empty-character-class": "warn",
  "no-empty-function": ["error", {"allow": []}],
  "no-empty-pattern": ["warn", {"allowObjectPatternsAsParameters": false}],
  "no-empty-static-block": "warn",
  "no-eval": ["error", {"allowIndirect": false}],
  "no-ex-assign": "warn",
  "no-extra-bind": "error",
  "no-extra-boolean-cast": ["warn", {}],
  "no-extra-label": "warn",
  "no-fallthrough": ["error", {"allowEmptyCase": false, "reportUnusedFallthroughComment": false}],
  "no-global-assign": ["warn", {"exceptions": []}],
  "no-invalid-regexp": ["warn", {}],
  "no-irregular-whitespace": [
    "warn",
    {
      "skipComments": false,
      "skipJSXText": false,
      "skipRegExps": false,
      "skipStrings": false,
      "skipTemplates": false
    }
  ],
  "no-iterator": "error",
  "no-lonely-if": "warn",
  "no-loss-of-precision": "warn",
  "no-misleading-character-class": ["warn", {"allowEscape": false}],
  "no-nonoctal-decimal-escape": "warn",
  "no-param-reassign": "error",
  "no-promise-executor-return": ["warn", {"allowVoid": false}],
  "no-proto": "error",
  "no-prototype-builtins": "error",
  "no-regex-spaces": "warn",
  "no-restricted-properties": [
    "error",
    {
      "object": "arguments",
      "property": "callee",
      "message": "Use a named function reference instead of legacy arguments introspection."
    },
    {
      "object": "arguments",
      "property": "caller",
      "message": "Pass context explicitly instead of inspecting the caller."
    },
    {
      "object": "process",
      "property": "nextTick",
      "message": "Prefer queueMicrotask()."
    },
    {
      "object": "Number",
      "property": "NaN",
      "message": "Use NaN."
    },
    {
      "object": "Number",
      "property": "POSITIVE_INFINITY",
      "message": "Use Infinity."
    },
    {
      "object": "Number",
      "property": "NEGATIVE_INFINITY",
      "message": "Use -Infinity."
    },
    {
      "object": "Number",
      "property": "isInteger",
      "message": "Use Number.isSafeInteger()."
    }
  ],
  "no-return-assign": ["warn", "except-parens"],
  "no-self-assign": ["warn", {"props": true}],
  "no-self-compare": "warn",
  "no-shadow": "error",
  "no-shadow-restricted-names": ["warn", {"reportGlobalThis": true}],
  "no-sparse-arrays": "warn",
  "no-template-curly-in-string": "warn",
  "no-unassigned-vars": "warn",
  "no-unexpected-multiline": "warn",
  "no-unmodified-loop-condition": ["warn", {"checkConditionalExpressions": false}],
  "no-unreachable-loop": ["warn", {"ignore": []}],
  "no-unsafe-finally": "error",
  "no-unsafe-optional-chaining": ["error", {"disallowArithmeticOperators": false}],
  "no-unused-expressions": ["error", {"allowShortCircuit": false, "allowTaggedTemplates": false, "allowTernary": false}],
  "no-unused-labels": "warn",
  "no-unused-private-class-members": "warn",
  "no-unused-vars": [
    "error",
    {
      "argsIgnorePattern": "^_",
      "varsIgnorePattern": "^_",
      "caughtErrorsIgnorePattern": "^_",
      "ignoreRestSiblings": true
    }
  ],
  "no-useless-assignment": "warn",
  "no-useless-backreference": "warn",
  "no-useless-catch": "warn",
  "no-useless-computed-key": ["error", {"enforceForClassMembers": true}],
  "no-useless-concat": "error",
  "no-useless-constructor": "error",
  "no-useless-escape": ["warn", {"allowRegexCharacters": []}],
  "no-useless-rename": ["error", {"ignoreDestructuring": false, "ignoreImport": false, "ignoreExport": false}],
  "no-useless-return": "error",
  "no-var": "error",
  "object-shorthand": ["error", "always"],
  "prefer-arrow-callback": ["error", {"allowNamedFunctions": true, "allowUnboundThis": true}],
  "prefer-const": ["error", {"destructuring": "any", "ignoreReadBeforeAssign": false}],
  "prefer-object-has-own": "error",
  "prefer-rest-params": "error",
  "prefer-spread": "error",
  "prefer-template": "error",
  "require-yield": "warn",
  "use-isnan": ["warn", {"enforceForIndexOf": false, "enforceForSwitchCase": true}],
  "valid-typeof": ["warn", {"requireStringLiterals": false}],

  // typescript-eslint (native; type-aware ones run through tsrs-lint).
  "typescript/adjacent-overload-signatures": "error",
  "typescript/array-type": "error",
  "typescript/await-thenable": "error",
  "typescript/ban-ts-comment": ["error", {"minimumDescriptionLength": 10}],
  "typescript/ban-tslint-comment": "error",
  "typescript/class-literal-property-style": "error",
  "typescript/consistent-generic-constructors": "error",
  "typescript/consistent-indexed-object-style": ["error", "record"],
  "typescript/consistent-type-assertions": ["error", {"assertionStyle": "never"}],
  "typescript/consistent-type-definitions": "error",
  "typescript/consistent-type-exports": ["error", {"fixMixedExportsWithInlineTypeSpecifier": true}],
  "typescript/consistent-type-imports": ["error", {"prefer": "type-imports", "fixStyle": "inline-type-imports"}],
  "typescript/dot-notation": [
    "error",
    {
      "allowIndexSignaturePropertyAccess": false,
      "allowKeywords": true,
      "allowPattern": "^[A-Za-z_$][\\w$]*_[\\w$]*$",
      "allowPrivateClassPropertyAccess": false,
      "allowProtectedClassPropertyAccess": false
    }
  ],
  "typescript/no-array-delete": "error",
  "typescript/no-base-to-string": "error",
  "typescript/no-confusing-non-null-assertion": "error",
  "typescript/no-confusing-void-expression": ["error", {"ignoreArrowShorthand": true}],
  "typescript/no-deprecated": "error",
  "typescript/no-duplicate-enum-values": "error",
  "typescript/no-duplicate-type-constituents": "error",
  "typescript/no-dynamic-delete": "error",
  "typescript/no-empty-object-type": "error",
  "typescript/no-explicit-any": "error",
  "typescript/no-extra-non-null-assertion": "error",
  "typescript/no-extraneous-class": "error",
  "typescript/no-floating-promises": ["error", {"ignoreVoid": false}],
  "typescript/no-generated-empty-object-type": "error",
  "typescript/no-implied-eval": "error",
  "typescript/no-import-type-side-effects": "error",
  "typescript/no-invalid-void-type": "error",
  "typescript/no-meaningless-void-operator": "error",
  "typescript/no-misused-new": "error",
  "typescript/no-misused-promises": ["error", {"checksVoidReturn": {"attributes": false}}],
  "typescript/no-misused-spread": "error",
  "typescript/no-mixed-enums": "error",
  "typescript/no-namespace": "error",
  "typescript/no-non-null-asserted-nullish-coalescing": "error",
  "typescript/no-non-null-asserted-optional-chain": "error",
  "typescript/no-non-null-assertion": "error",
  "typescript/no-redundant-type-constituents": "error",
  "typescript/no-require-imports": "error",
  "typescript/no-this-alias": "error",
  "typescript/no-unnecessary-boolean-literal-compare": "error",
  "typescript/no-unnecessary-condition": "error",
  "typescript/no-unnecessary-qualifier": "error",
  "typescript/no-unnecessary-template-expression": "error",
  "typescript/no-unnecessary-type-arguments": "error",
  "typescript/no-unnecessary-type-assertion": ["error", {"checkLiteralConstAssertions": true}],
  "typescript/no-unnecessary-type-constraint": "error",
  "typescript/no-unnecessary-type-conversion": "error",
  "typescript/no-unnecessary-type-parameters": "error",
  "typescript/no-unsafe-argument": "error",
  "typescript/no-unsafe-assignment": "error",
  "typescript/no-unsafe-call": "error",
  "typescript/no-unsafe-declaration-merging": "error",
  "typescript/no-unsafe-enum-assignment": "error",
  "typescript/no-unsafe-enum-comparison": "error",
  "typescript/no-unsafe-function-type": "error",
  "typescript/no-unsafe-member-access": "error",
  "typescript/no-unsafe-return": "error",
  "typescript/no-unsafe-type-assertion": "error",
  "typescript/no-unsafe-unary-minus": "error",
  "typescript/no-useless-default-assignment": "error",
  "typescript/no-useless-empty-export": "error",
  "typescript/no-wrapper-object-types": "error",
  "typescript/non-nullable-type-assertion-style": "error",
  "typescript/only-throw-error": ["error", {"allow": [{"from": "package", "package": "@tanstack/react-router", "name": ["redirect"]}]}],
  "typescript/prefer-as-const": "error",
  "typescript/prefer-find": "error",
  "typescript/prefer-for-of": "error",
  "typescript/prefer-function-type": "error",
  "typescript/prefer-includes": "error",
  "typescript/prefer-literal-enum-member": "error",
  "typescript/prefer-namespace-keyword": "error",
  "typescript/prefer-nullish-coalescing": ["error", {"ignoreBooleanCoercion": true}],
  "typescript/prefer-optional-chain": "error",
  "typescript/prefer-promise-reject-errors": "error",
  "typescript/prefer-readonly": "error",
  "typescript/prefer-reduce-type-parameter": "error",
  "typescript/prefer-regexp-exec": "error",
  "typescript/prefer-return-this-type": "error",
  "typescript/prefer-string-starts-ends-with": "error",
  "typescript/related-getter-setter-pairs": "error",
  "typescript/require-array-sort-compare": "error",
  "typescript/require-await": "error",
  "typescript/restrict-plus-operands": [
    "error",
    {
      "allowAny": false,
      "allowBoolean": false,
      "allowNullish": false,
      "allowNumberAndString": false,
      "allowRegExp": false
    }
  ],
  "typescript/restrict-template-expressions": [
    "error",
    {
      "allowAny": false,
      "allowBoolean": false,
      "allowNever": false,
      "allowNullish": false,
      "allowNumber": false,
      "allowRegExp": false
    }
  ],
  "typescript/return-await": ["error", "error-handling-correctness-only"],
  "typescript/strict-void-return": "warn",
  "typescript/switch-exhaustiveness-check": "error",
  "typescript/triple-slash-reference": "error",
  "typescript/unbound-method": "error",
  "typescript/unified-signatures": "error",
  "typescript/use-unknown-in-catch-callback-variable": "error",

  // Unicorn (native).
  "unicorn/consistent-assert": "error",
  "unicorn/consistent-date-clone": "error",
  "unicorn/consistent-empty-array-spread": "error",
  "unicorn/consistent-function-scoping": ["error", {"checkArrowFunctions": true}],
  "unicorn/custom-error-definition": "warn",
  "unicorn/error-message": "error",
  "unicorn/explicit-timer-delay": ["error", "always"],
  "unicorn/filename-case": ["error", {"cases": {"kebabCase": true}, "ignore": ["^__root\\.", "^_", "^\\$", "^\\+", "\\.gen\\."]}],
  "unicorn/new-for-builtins": "error",
  "unicorn/no-abusive-eslint-disable": "error",
  "unicorn/no-accessor-recursion": "error",
  "unicorn/no-array-fill-with-reference-type": "error",
  "unicorn/no-array-method-this-argument": "error",
  "unicorn/no-array-reverse": ["error", {"allowExpressionStatement": true}],
  "unicorn/no-array-sort": ["error", {"allowExpressionStatement": true}],
  "unicorn/no-await-expression-member": "error",
  "unicorn/no-await-in-promise-methods": "error",
  "unicorn/no-confusing-array-with": "error",
  "unicorn/no-document-cookie": "error",
  "unicorn/no-empty-file": "error",
  "unicorn/no-instanceof-builtins": ["error", {"useErrorIsError": false, "strategy": "loose", "include": [], "exclude": []}],
  "unicorn/no-invalid-fetch-options": "error",
  "unicorn/no-invalid-remove-event-listener": "error",
  "unicorn/no-lonely-if": "warn",
  "unicorn/no-magic-array-flat-depth": "error",
  "unicorn/no-negation-in-equality-check": "error",
  "unicorn/no-new-buffer": "error",
  "unicorn/no-object-as-default-parameter": "error",
  "unicorn/no-single-promise-in-promise-methods": "error",
  "unicorn/no-this-assignment": "error",
  "unicorn/no-typeof-undefined": ["error", {"checkGlobalVariables": false}],
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
  "unicorn/no-useless-spread": "error",
  "unicorn/prefer-add-event-listener": "error",
  "unicorn/prefer-array-flat": "error",
  "unicorn/prefer-array-flat-map": "error",
  "unicorn/prefer-array-index-of": "error",
  "unicorn/prefer-array-some": "error",
  "unicorn/prefer-at": ["error", {"getLastElementFunctions": [], "checkAllIndexAccess": false}],
  "unicorn/prefer-bigint-literals": "error",
  "unicorn/prefer-blob-reading-methods": "error",
  "unicorn/prefer-class-fields": "error",
  "unicorn/prefer-code-point": "error",
  "unicorn/prefer-date-now": "error",
  "unicorn/prefer-default-parameters": "error",
  "unicorn/prefer-event-target": "error",
  "unicorn/prefer-export-from": ["error", {"checkUsedVariables": true}],
  "unicorn/prefer-import-meta-properties": "error",
  "unicorn/prefer-keyboard-event-key": "error",
  "unicorn/prefer-math-min-max": "error",
  "unicorn/prefer-math-trunc": "error",
  "unicorn/prefer-modern-math-apis": "error",
  "unicorn/prefer-module": "error",
  "unicorn/prefer-native-coercion-functions": "error",
  "unicorn/prefer-negative-index": "error",
  "unicorn/prefer-node-protocol": "error",
  "unicorn/prefer-number-properties": ["error", {"checkInfinity": false, "checkNaN": false}],
  "unicorn/prefer-object-from-entries": ["error", {"functions": []}],
  "unicorn/prefer-optional-catch-binding": "error",
  "unicorn/prefer-regexp-test": "error",
  "unicorn/prefer-response-static-json": "error",
  "unicorn/prefer-set-has": "error",
  "unicorn/prefer-set-size": "error",
  "unicorn/prefer-spread": "error",
  "unicorn/prefer-string-raw": "error",
  "unicorn/prefer-string-replace-all": "error",
  "unicorn/prefer-string-slice": "error",
  "unicorn/prefer-string-trim-start-end": "error",
  "unicorn/prefer-structured-clone": ["error", {"functions": []}],
  "unicorn/relative-url-style": ["error", "never"],
  "unicorn/require-array-join-separator": "error",
  "unicorn/require-module-attributes": "error",
  "unicorn/require-module-specifiers": "error",
  "unicorn/require-number-to-fixed-digits-argument": "error",
  "unicorn/require-post-message-target-origin": "error",
  "unicorn/text-encoding-identifier-case": ["error", {"withDash": false}],
  "unicorn/throw-new-error": "error",

  // React and the React Compiler checks of eslint-plugin-react-hooks (native).
  "react/button-has-type": "error",
  "react/error-boundaries": "error",
  "react/exhaustive-deps": "error",
  "react/globals": "error",
  "react/immutability": "error",
  "react/incompatible-library": "error",
  "react/jsx-boolean-value": ["error", "never"],
  "react/jsx-curly-brace-presence": ["error", {"props": "never", "children": "never", "propElementValues": "always"}],
  "react/jsx-fragments": "error",
  "react/jsx-key": "error",
  "react/jsx-no-comment-textnodes": "error",
  "react/jsx-no-duplicate-props": "error",
  "react/jsx-no-script-url": "error",
  "react/jsx-no-target-blank": "error",
  "react/jsx-no-undef": "error",
  "react/jsx-no-useless-fragment": "error",
  "react/jsx-pascal-case": "error",
  "react/no-children-prop": "error",
  "react/no-danger": "error",
  "react/no-object-type-as-default-prop": "error",
  "react/no-this-in-sfc": "error",
  "react/no-unknown-property": "error",
  "react/preserve-manual-memoization": "error",
  "react/purity": "error",
  "react/refs": "error",
  "react/rules-of-hooks": "error",
  "react/self-closing-comp": "error",
  "react/set-state-in-effect": "error",
  "react/set-state-in-render": "error",
  "react/static-components": "error",
  "react/style-prop-object": "error",
  "react/unsupported-syntax": "error",
  "react/use-memo": "error",
  "react/void-dom-elements-no-children": "error",
  "react/void-use-memo": "error",

  // import (native).
  "import/export": "error",

  // promise (native).
  "promise/prefer-catch": "error",

  // oxc (native).
  "oxc/approx-constant": "error",
  "oxc/bad-bitwise-operator": "error",
  "oxc/bad-char-at-comparison": "error",
  "oxc/bad-comparison-sequence": "error",
  "oxc/bad-match-all-arg": "warn",
  "oxc/bad-replace-all-arg": "warn",
  "oxc/const-comparisons": "error",
  "oxc/double-comparisons": "error",
  "oxc/erasing-op": "error",
  "oxc/misrefactored-assign-op": "error",

  // Suppression policy: @sarj ports of @eslint-community/eslint-comments that read eslint-* and oxlint-* directives.
  "@sarj/no-oxlint-directive": "warn",
  "@sarj/directive-disable-enable-pair": ["warn", {"allowWholeFile": false}],
  "@sarj/directive-no-aggregating-enable": "warn",
  "@sarj/directive-no-duplicate-disable": "warn",
  "@sarj/directive-no-restricted-disable": ["warn", "no-console", "react-hooks/exhaustive-deps", "react/exhaustive-deps", "@sarj/no-vague-suppression-description"],
  "@sarj/directive-no-unused-enable": "warn",
  "@sarj/directive-no-use": [
    "warn",
    {
      "allow": [
        "eslint-disable-line",
        "eslint-disable-next-line",
        "eslint-env",
        "exported",
        "global",
        "globals"
      ]
    }
  ],
  "@sarj/directive-require-description": ["warn", {"ignore": []}],

  // ESLint core rules without a native port, or whose port reports differently (oxlint-plugin-eslint).
  "eslint-js/no-restricted-syntax": [
    "error",
    {
      "selector": "ForInStatement",
      "message": "Do not use for-in enumeration. Use for-of with Object.keys or Object.entries for own properties; an inherited-key protocol requires an exact, explained exception."
    },
    {
      "selector": ":matches(TSAsExpression, TSTypeAssertion)[typeAnnotation.typeName.name='const'] > ObjectExpression > Property > :matches(TSAsExpression, TSTypeAssertion).value[typeAnnotation.typeName.name='const'], :matches(TSAsExpression, TSTypeAssertion)[typeAnnotation.typeName.name='const'] > ArrayExpression > :matches(TSAsExpression, TSTypeAssertion)[typeAnnotation.typeName.name='const']",
      "message": "This member already inherits the enclosing as const assertion. Remove the member's redundant const assertion."
    },
    {
      "selector": "CallExpression[callee.property.name='forEach']",
      "message": "Prefer a for-of loop over forEach."
    },
    {
      "selector": "TSModuleDeclaration[kind='namespace']",
      "message": "Use ES modules instead of namespaces."
    }
  ],
  "eslint-js/preserve-caught-error": ["warn", {"requireCatchParameter": true, "errorClassNames": []}],

  // Unicorn rules without a native port, or whose port reports differently.
  "unicorn-js/class-reference-in-static-methods": ["error", {"preferThis": true, "preferSuper": true}],
  "unicorn-js/consistent-json-file-read": ["error", "string"],
  "unicorn-js/no-array-concat-in-loop": "error",
  "unicorn-js/no-array-from-fill": "error",
  "unicorn-js/no-array-sort-for-min-max": "error",
  "unicorn-js/no-async-iterator-callback": "error",
  "unicorn-js/no-async-promise-finally": "error",
  "unicorn-js/no-blob-to-file": "error",
  "unicorn-js/no-canvas-to-image": "error",
  "unicorn-js/no-computed-property-existence-check": "warn",
  "unicorn-js/no-conflicting-constraints": "error",
  "unicorn-js/no-confusing-array-splice": "error",
  "unicorn-js/no-duplicate-if-branches": "error",
  "unicorn-js/no-duplicate-loops": "error",
  "unicorn-js/no-duplicate-set-values": "error",
  "unicorn-js/no-error-property-assignment": "error",
  "unicorn-js/no-exports-in-scripts": "error",
  "unicorn-js/no-immediate-mutation": ["error", {"checkConditionals": false}],
  "unicorn-js/no-impossible-length-comparison": "error",
  "unicorn-js/no-incomplete-accessor-override": "error",
  "unicorn-js/no-incorrect-template-string-interpolation": "error",
  "unicorn-js/no-ineffective-csp-directives": "error",
  "unicorn-js/no-invalid-boolean-attribute-value": "error",
  "unicorn-js/no-invalid-dom-token": "error",
  "unicorn-js/no-invalid-file-input-accept": "error",
  "unicorn-js/no-invalid-integrity": "error",
  "unicorn-js/no-invalid-response-options": "error",
  "unicorn-js/no-invalid-style-set-property": "error",
  "unicorn-js/no-invalid-temporal-arithmetic": "error",
  "unicorn-js/no-invalid-url-protocol-comparison": "error",
  "unicorn-js/no-invalid-well-known-symbol-methods": "error",
  "unicorn-js/no-late-current-target-access": "error",
  "unicorn-js/no-late-event-control": "error",
  "unicorn-js/no-loop-iterable-mutation": "error",
  "unicorn-js/no-mismatched-map-key": "error",
  "unicorn-js/no-missing-local-resource": "error",
  "unicorn-js/no-multiple-promise-resolver-calls": "error",
  "unicorn-js/no-object-methods-with-collections": "error",
  "unicorn-js/no-prevent-default-in-passive-listener": "error",
  "unicorn-js/no-redundant-comparison": "error",
  "unicorn-js/no-return-array-push": "error",
  "unicorn-js/no-selector-as-dom-name": "error",
  "unicorn-js/no-shorthand-property-overrides": "error",
  "unicorn-js/no-subtraction-comparison": "error",
  "unicorn-js/no-uncalled-method": "error",
  "unicorn-js/no-unnecessary-array-flat-map": "error",
  "unicorn-js/no-unnecessary-default-arguments": "error",
  "unicorn-js/no-unnecessary-fetch-options": "error",
  "unicorn-js/no-unnecessary-global-this": "error",
  "unicorn-js/no-unnecessary-nested-ternary": "error",
  "unicorn-js/no-unnecessary-parameters": ["error", {"minimumCallCount": 2}],
  "unicorn-js/no-unnecessary-polyfills": ["error", {}],
  "unicorn-js/no-unnecessary-splice": "error",
  "unicorn-js/no-unnecessary-string-trim": "error",
  "unicorn-js/no-unsafe-buffer-conversion": "error",
  "unicorn-js/no-unsafe-dom-html": "error",
  "unicorn-js/no-unsafe-json-serialization": "error",
  "unicorn-js/no-unsafe-sqlite-interpolation": "error",
  "unicorn-js/no-unsafe-string-replacement": "error",
  "unicorn-js/no-unused-builtin-method-return": "error",
  "unicorn-js/no-unused-iterator-helper": "error",
  "unicorn-js/no-url-in-search-params": "error",
  "unicorn-js/no-useless-boolean-cast": "error",
  "unicorn-js/no-useless-compound-assignment": "error",
  "unicorn-js/no-useless-continue": "error",
  "unicorn-js/no-useless-delete-check": "error",
  "unicorn-js/no-useless-override": "error",
  "unicorn-js/no-useless-recursion": "error",
  "unicorn-js/no-useless-set-construction": "error",
  "unicorn-js/no-xor-as-exponentiation": "error",
  "unicorn-js/prefer-add-event-listener-options": "error",
  "unicorn-js/prefer-combined-guards": ["warn", {"checkCompoundConditions": false, "checkMultiStatementBodies": false}],
  "unicorn-js/prefer-iterator-to-array": "error",
  "unicorn-js/prefer-logical-operator-over-ternary": "error",
  "unicorn-js/prefer-single-object-destructuring": "warn",
  "unicorn-js/prefer-top-level-await": "error",
  "unicorn-js/prefer-type-error": "error",
  "unicorn-js/require-css-escape": ["error", {"checkAllSelectors": false}],
  "unicorn-js/require-passive-events": "error",
  "unicorn-js/require-text-decoder-streaming": "error",

  // jsdoc (JS plugin).
  "jsdoc-js/no-restricted-syntax": [
    "error",
    {
      "contexts": [
        {
          "context": "ArrowFunctionExpression",
          "message": "Do not attach JSDoc to an implementation; keep only behavior that the code or tests cannot express."
        },
        {
          "context": "FunctionDeclaration[body.type='BlockStatement']",
          "message": "Do not attach JSDoc to an implementation; keep only behavior that the code or tests cannot express."
        },
        {
          "context": "FunctionExpression[body.type='BlockStatement']",
          "message": "Do not attach JSDoc to an implementation; keep only behavior that the code or tests cannot express."
        }
      ]
    }
  ],

  // eslint-plugin-react rules without a native port.
  "react-js/jsx-no-leaked-render": ["error", {"validStrategies": ["ternary", "coerce"]}],
  "react-js/no-invalid-html-attribute": "error",

  // regexp.
  "regexp/no-contradiction-with-assertion": "warn",
  "regexp/no-useless-assertions": "warn",

  // security.
  "security/detect-bidi-characters": "error",
  "security/detect-child-process": "warn",

  // zod.
  "zod/no-any-schema": "error",
  "zod/no-coerce-boolean": "error",
  "zod/no-conflicting-checks": "error",
  "zod/no-duplicate-schema-methods": "error",
  "zod/no-throw-in-refine": "error",
  "zod/no-transform-in-record-key": "error",

  // @sarj: every rule at its policy level. config_generation renders the warn/error levels from the rule catalog.
  "@sarj/duplicate-test-body": "error",
  "@sarj/enforce-file-structure": "error",
  "@sarj/excessive-commentary": "warn",
  "@sarj/iac-source-coupled-test": "error",
  "@sarj/interface-contract-members-private": "error",
  "@sarj/named-child-schema-type": "error",
  "@sarj/no-bare-return-from-test-catch": "error",
  "@sarj/no-bespoke-api-case-conversion": "warn",
  "@sarj/no-boolean-selector-parameter": "warn",
  "@sarj/no-broad-return-type": "error",
  "@sarj/no-client-side-data-fetching": "error",
  "@sarj/no-comment-cruft": "error",
  "@sarj/no-conditional-empty-object-spread": "error",
  "@sarj/no-contradictory-overload-return": "error",
  "@sarj/no-contradictory-type-predicate": "error",
  "@sarj/no-cors-wildcard-with-credentials": "warn",
  "@sarj/no-credential-in-browser-storage": "warn",
  "@sarj/no-dangerously-allow-svg": "error",
  "@sarj/no-declaration-comment-wall": [
    "error",
    {
      "minCommentedMembers": 3,
      "minCommentedRatio": 0.6,
      "minRestatedRatio": 0.75,
      "maxNovelWords": 1
    }
  ],
  "@sarj/no-detached-global-fetch": "error",
  "@sarj/no-discarded-validation-result": "warn",
  "@sarj/no-duplicate-lifecycle-refresh-listeners": "error",
  "@sarj/no-duplicate-test-case": "error",
  "@sarj/no-dynamic-sql": ["error", {}],
  "@sarj/no-enum": ["error", {}],
  "@sarj/no-exception-text-in-5xx-response": "warn",
  "@sarj/no-excess-jsx-props": "warn",
  "@sarj/no-excessive-cognitive-complexity": "error",
  "@sarj/no-explicit-type-predicate": "warn",
  "@sarj/no-fat-try-blocks": ["error", {"max": 5}],
  "@sarj/no-first-party-module-mock": ["error", {"additionalModulePrefixes": []}],
  "@sarj/no-frontend-comments": ["error", {}],
  "@sarj/no-generic-json-parser": "warn",
  "@sarj/no-generic-single-export-module": "error",
  "@sarj/no-growing-array-spread-in-loop": "warn",
  "@sarj/no-hand-rolled-sleep": ["error", {}],
  "@sarj/no-hand-rolled-spinner": "error",
  "@sarj/no-impossible-zod-literal-bounds": ["error", {"delegateRealContradictions": true}],
  "@sarj/no-in-operator-on-built-in-collections": "error",
  "@sarj/no-insecure-random-id": "error",
  "@sarj/no-invalid-typed-mutation": "error",
  "@sarj/no-invalid-zod-custom-parse": "error",
  "@sarj/no-json-stringify-error": "error",
  "@sarj/no-json-stringify-object-equality": "error",
  "@sarj/no-known-value-widening": "error",
  "@sarj/no-log-only-catch": ["error", {}],
  "@sarj/no-logical-or-fallback": "warn",
  "@sarj/no-long-comment": "error",
  "@sarj/no-mutating-container-transform": "warn",
  "@sarj/no-mutating-input-with-result": "warn",
  "@sarj/no-negative-only-http-status-assertion": "warn",
  "@sarj/no-numeric-search-param-coercion": "warn",
  "@sarj/no-offset-pagination": "error",
  "@sarj/no-partial-type-predicate": "error",
  "@sarj/no-positional-tuple-return": "error",
  "@sarj/no-production-browser-source-maps": "error",
  "@sarj/no-raw-env": "error",
  "@sarj/no-raw-fetch-outside-clients": ["error", {}],
  "@sarj/no-readonly-prop-state": "warn",
  "@sarj/no-reduce-accumulator-copy": "error",
  "@sarj/no-redundant-consumer-union": "warn",
  "@sarj/no-redundant-local-alias": "warn",
  "@sarj/no-redundant-optional-array-default": "error",
  "@sarj/no-repeated-string-literal": "error",
  "@sarj/no-restated-comment": "warn",
  "@sarj/no-restated-jsdoc": "warn",
  "@sarj/no-return-disposed-resource": "warn",
  "@sarj/no-router-refresh-polling": "error",
  "@sarj/no-runtime-typeof": "error",
  "@sarj/no-secret-in-log": ["error", {}],
  "@sarj/no-select-star": "error",
  "@sarj/no-sentinel-return-on-catch": ["error", {}],
  "@sarj/no-server-env-in-client-component": "error",
  "@sarj/no-server-file-uploads": "error",
  "@sarj/no-silent-promise-catch": "error",
  "@sarj/no-sleep-in-test-body": "error",
  "@sarj/no-string-concat-in-loop": "error",
  "@sarj/no-tautological-expect": "error",
  "@sarj/no-test-comments": ["error", {}],
  "@sarj/no-trailing-value-narration": "error",
  "@sarj/no-type-member-comment-wall": [
    "error",
    {
      "minCommentedMembers": 3,
      "minCommentedRatio": 0.6,
      "minRestatedRatio": 0.75,
      "maxNovelWords": 1
    }
  ],
  "@sarj/no-typed-doc-sections": "error",
  "@sarj/no-union-in-comment": "error",
  "@sarj/no-unlocalized-jsx-attributes": ["error", {"enabled": false}],
  "@sarj/no-unlocalized-jsx-text": ["error", {"enabled": false}],
  "@sarj/no-unlocalized-toast": ["error", {"enabled": false}],
  "@sarj/no-unnecessary-use-client": "error",
  "@sarj/no-unsafe-mock-casting": "error",
  "@sarj/no-unsafe-test-double-cast": "error",
  "@sarj/no-vague-suppression-description": "error",
  "@sarj/no-zod-native-enum": "error",
  "@sarj/no-zod-parse-typed-object": "warn",
  "@sarj/prefer-await-in-async-return": ["error", {"scope": "all-promise-calls"}],
  "@sarj/prefer-coded-error-result": "warn",
  "@sarj/prefer-constant-time-secret-compare": "error",
  "@sarj/prefer-dependency-interface": "warn",
  "@sarj/prefer-discriminated-union": "warn",
  "@sarj/prefer-ecmascript-private-members": "error",
  "@sarj/prefer-immutable-module-constant": "error",
  "@sarj/prefer-input-group-search": "error",
  "@sarj/prefer-logical-tailwind-utilities": ["error", {"enabled": false, "checkInsets": false, "allowUtilities": []}],
  "@sarj/prefer-millisecond-control-duration-schema": "warn",
  "@sarj/prefer-minimal-parameter-contract": "warn",
  "@sarj/prefer-module-level-constant": ["error", {}],
  "@sarj/prefer-module-level-refined-schema": "warn",
  "@sarj/prefer-module-level-schema": ["error", {}],
  "@sarj/prefer-multi-value-zod-literal": ["error", {"zodMajorVersion": 4}],
  "@sarj/prefer-named-callback-domain": "error",
  "@sarj/prefer-named-complex-return-type": "error",
  "@sarj/prefer-native-fetch-in-server-actions": "warn",
  "@sarj/prefer-native-random-uuid": "error",
  "@sarj/prefer-node-crypto-hash": "warn",
  "@sarj/prefer-node-fs-promises": "warn",
  "@sarj/prefer-nominal-id-types": "error",
  "@sarj/prefer-non-nullable-collection": "error",
  "@sarj/prefer-nullish-filter-predicate": "error",
  "@sarj/prefer-schema-for-api-payload": "error",
  "@sarj/prefer-semantic-colors": ["error", {"requireSemanticTokens": true}],
  "@sarj/prefer-server-actions": ["error", {}],
  "@sarj/prefer-server-data-preparation": "warn",
  "@sarj/prefer-shadcn-primitives": ["error", {}],
  "@sarj/prefer-shared-zod-enum": "warn",
  "@sarj/prefer-switch-for-repeated-equality": "error",
  "@sarj/prefer-test-fixture-reuse": "warn",
  "@sarj/prefer-typed-reflection": "error",
  "@sarj/prefer-whole-object-assertion": "warn",
  "@sarj/prefer-zod-enum-validator": "warn",
  "@sarj/prefer-zod-infer": ["error", {}],
  "@sarj/prefer-zod-parse-output-type": "warn",
  "@sarj/production-derived-test-cases": "warn",
  "@sarj/repeated-static-call-cases": "error",
  "@sarj/require-assert-never": "error",
  "@sarj/require-button-accessible-name": ["error", {}],
  "@sarj/require-camelcase-properties": "error",
  "@sarj/require-constrained-schema-integer": "warn",
  "@sarj/require-explicit-contract-implementation": "error",
  "@sarj/require-explicit-service-contract": "error",
  "@sarj/require-fetch-timeout": ["error", {}],
  "@sarj/require-interface-for-exported-class": "error",
  "@sarj/require-jwt-lifetime": "warn",
  "@sarj/require-pascal-case-zod-schema-name": "error",
  "@sarj/require-port-for-service": "error",
  "@sarj/require-sql-access-class": "warn",
  "@sarj/require-static-next-matcher": "error",
  "@sarj/require-svg-accessible-name": "error",
  "@sarj/require-use-form-default-values": "error",
  "@sarj/require-use-server-in-actions-file": "error",
  "@sarj/require-zod-form-validation": "error",
  "@sarj/sole-export-matches-filename": "error",
  "@sarj/source-coupled-test": "error",
  "@sarj/stepdown": ["error", {"privateBandOnly": true}],
  "@sarj/store-insert-requires-on-conflict": "error",
  "@sarj/test-loops-over-literal-cases": "error",
  "@sarj/test-phase-label-comment": "error",
  "no-restricted-imports": [
    "error",
    {
      paths: [
        ...LIBRARY_IMPORT_PATHS,
        { name: "@clerk/nextjs", importNames: ["auth", "currentUser"], message: "Prefer an internal user-service wrapper." },
        { name: "@clerk/nextjs/server", message: "Prefer an internal user-service wrapper." },
      ],
      patterns: [{ group: ["*/index", "*/index.ts"] }, ...LIBRARY_IMPORT_PATTERNS],
    },
  ],
  "@sarj/no-restricted-library-load": ["error", { libraries: LIBRARY_LOADS }],

  // Added with the switch to Oxlint (packages/typescript/scripts/oxlint/stage2-rule-additions.json).
  "@tanstack/query/exhaustive-deps": "error",
  "@tanstack/query/prefer-query-options": "warn",
  "react/no-array-index-key": "error",
  "@eslint-react/jsx-no-key-after-spread": "error",
  "@eslint-react/web-api-no-leaked-event-listener": "warn",
  "@eslint-react/web-api-no-leaked-timeout": "warn",
  "@eslint-react/web-api-no-leaked-interval": "warn",
  "@eslint-react/web-api-no-leaked-resize-observer": "warn",
  "effects/no-pass-live-state-to-parent": "warn",
  "effects/no-pass-data-to-parent": "warn",
  "react/iframe-missing-sandbox": "error",
  "@eslint-react/dom-no-unsafe-iframe-sandbox": "error",
  "oxc/bad-min-max-func": "error",
  "oxc/bad-object-literal-comparison": "error",
  "oxc/missing-throw": "error",
  "oxc/number-arg-out-of-range": "error",
  "oxc/uninvoked-array-callback": "error",
  "oxc/only-used-in-recursion": "error",
  "oxc/bad-array-method-on-arguments": "error",
  "radix": "error",
  "import/no-duplicates": "warn",
  "typescript/no-unnecessary-parameter-property-assignment": "error",
  "react/capitalized-calls": "error",
  "react/hooks": "error",
  "react/memo-dependencies": "error",
  "react/invariant": "error",
  "react/syntax": "error",
  "react/rule-suppression": "error",
} satisfies OxlintConfig["rules"];

// Vitest rules: on in tests when Vitest is a test framework, off in Bun and Playwright tests.
const VITEST_RULES = {
  "vitest/expect-expect": ["warn", {"assertFunctionNames": ["expect", "assert"], "additionalTestBlockFunctions": []}],
  "vitest/no-focused-tests": "warn",
  "vitest/prefer-called-once": "error",
  "vitest/prefer-expect-resolves": "error",
  "vitest/prefer-to-be": "error",
  "vitest/require-local-test-context-for-concurrent-snapshots": "warn",
  "vitest/valid-expect": ["warn", {"alwaysAwait": false, "asyncMatchers": ["toReject", "toResolve"], "minArgs": 1, "maxArgs": 2}],
  // Added with the switch to Oxlint.
  "vitest/hoisted-apis-on-top": "error",
  "vitest/require-awaited-expect-poll": "error",
  "vitest/valid-expect-in-promise": "error",
  "vitest/no-identical-title": "error",
  "vitest/no-duplicate-hooks": "error",
  "vitest/valid-describe-callback": "error",
  "vitest/valid-title": "error",
  "vitest/no-disabled-tests": "error",
  "vitest/no-conditional-expect": "warn",
} satisfies OxlintConfig["rules"];

const NODE_TEST_RULES = {
  "node-test/no-assert-throws-async": "error",
  "node-test/no-assert-throws-multiple-statements": "error",
  "node-test/no-callback-and-promise": "warn",
  "node-test/no-duplicate-mock-timers-enable": "warn",
  "node-test/no-late-test-activity": "warn",
  "node-test/no-mock-timers-destructured-import": "warn",
  "node-test/no-unneeded-async-rejects-callback": "error",
  "node-test/no-useless-assertion": "error",
} satisfies OxlintConfig["rules"];

const TESTING_LIBRARY_RULES = {
  "testing-library/await-async-events": "error",
  "testing-library/await-async-queries": "error",
  "testing-library/await-async-utils": "error",
  "testing-library/no-unnecessary-act": ["error", {"isStrict": false}],
  "testing-library/prefer-screen-queries": "error",
} satisfies OxlintConfig["rules"];

const PLAYWRIGHT_RULES = {
  "playwright/missing-playwright-await": "error",
  "playwright/no-unnecessary-assertions": "error",
  "playwright/no-unsafe-references": "warn",
} satisfies OxlintConfig["rules"];

// Type-aware rules, off in syntax-only config files.
const TYPE_AWARE_RULES = [
  "@sarj/no-boolean-selector-parameter",
  "typescript/await-thenable",
  "typescript/consistent-type-exports",
  "typescript/dot-notation",
  "typescript/no-array-delete",
  "typescript/no-base-to-string",
  "typescript/no-confusing-void-expression",
  "typescript/no-deprecated",
  "typescript/no-duplicate-type-constituents",
  "typescript/no-floating-promises",
  "typescript/no-generated-empty-object-type",
  "typescript/no-implied-eval",
  "typescript/no-meaningless-void-operator",
  "typescript/no-misused-promises",
  "typescript/no-misused-spread",
  "typescript/no-mixed-enums",
  "typescript/no-redundant-type-constituents",
  "typescript/no-unnecessary-boolean-literal-compare",
  "typescript/no-unnecessary-condition",
  "typescript/no-unnecessary-qualifier",
  "typescript/no-unnecessary-template-expression",
  "typescript/no-unnecessary-type-arguments",
  "typescript/no-unnecessary-type-assertion",
  "typescript/no-unnecessary-type-conversion",
  "typescript/no-unnecessary-type-parameters",
  "typescript/no-unsafe-argument",
  "typescript/no-unsafe-assignment",
  "typescript/no-unsafe-call",
  "typescript/no-unsafe-enum-assignment",
  "typescript/no-unsafe-enum-comparison",
  "typescript/no-unsafe-member-access",
  "typescript/no-unsafe-return",
  "typescript/no-unsafe-type-assertion",
  "typescript/no-unsafe-unary-minus",
  "typescript/no-useless-default-assignment",
  "typescript/non-nullable-type-assertion-style",
  "typescript/only-throw-error",
  "typescript/prefer-find",
  "typescript/prefer-includes",
  "typescript/prefer-nullish-coalescing",
  "typescript/prefer-optional-chain",
  "typescript/prefer-promise-reject-errors",
  "typescript/prefer-readonly",
  "typescript/prefer-reduce-type-parameter",
  "typescript/prefer-regexp-exec",
  "typescript/prefer-return-this-type",
  "typescript/prefer-string-starts-ends-with",
  "typescript/related-getter-setter-pairs",
  "typescript/require-array-sort-compare",
  "typescript/require-await",
  "typescript/restrict-plus-operands",
  "typescript/restrict-template-expressions",
  "typescript/return-await",
  "typescript/strict-void-return",
  "typescript/switch-exhaustiveness-check",
  "typescript/unbound-method",
  "typescript/use-unknown-in-catch-callback-variable",
] as const;

/** Build the managed config for the given test frameworks and file layout. */
export function createConfig(options: ConfigOptions = {}): OxlintConfig {
  const frameworks = new Set<TestFramework>(options.testFrameworks ?? ["vitest", "node"]);
  for (const framework of frameworks) {
    if (!TEST_FRAMEWORKS.includes(framework)) throw new Error(`Unsupported test framework ${JSON.stringify(framework)}`);
  }
  const vitest = frameworks.has("vitest");
  const bun = frameworks.has("bun");
  const node = frameworks.has("node");
  const testingLibrary = frameworks.has("testing-library");
  const playwright = frameworks.has("playwright");
  const syntaxOnlyConfigFiles = options.syntaxOnlyConfigFiles ?? DEFAULT_SYNTAX_ONLY_CONFIG_FILES;
  const vitestOff = Object.fromEntries(Object.keys(VITEST_RULES).map((rule) => [rule, "off"]));

  const overrides: OxlintOverride[] = [
    {
      files: JS_FILES,
      rules: {
        "constructor-super": "warn",
        "getter-return": ["warn", {"allowImplicit": false}],
        "jsdoc-js/no-restricted-syntax": [
          "error",
          {
            "contexts": [
              {
                "context": ":matches(ArrowFunctionExpression, FunctionDeclaration[body.type='BlockStatement'], FunctionExpression[body.type='BlockStatement'])",
                "comment": "JsdocBlock:not(:has(JsdocTag[parsedType])):not(:has(JsdocTag[tag='template']))",
                "message": "Do not attach untyped JSDoc to an implementation; preserve required type contracts."
              }
            ]
          }
        ],
        "no-class-assign": "warn",
        "no-const-assign": "warn",
        "no-dupe-class-members": "warn",
        "no-dupe-keys": "warn",
        "no-func-assign": "warn",
        "no-import-assign": "warn",
        "no-new-native-nonconstructor": "warn",
        "no-obj-calls": "warn",
        "no-redeclare": ["warn", {"builtinGlobals": true}],
        "no-setter-return": "warn",
        "no-this-before-super": "warn",
        "no-undef": ["warn", {"typeof": false}],
        "no-unreachable": "warn",
        "no-unsafe-negation": ["warn", {"enforceForOrderingRelations": false}],
        "no-with": "warn",
        "prefer-rest-params": "off",
        "prefer-spread": "off",
      },
    },
    // This rule has no JSX exception and would undo the async-handler policy;
    // no-misused-promises still checks non-JSX promise callback boundaries.
    { files: JSX_FILES, rules: { "typescript/strict-void-return": "off" } },
    {
      files: TEST_FILES,
      rules: {
        // Test doubles and partial fixtures cross type boundaries on purpose.
        "no-await-in-loop": "off",
        "typescript/consistent-type-assertions": "off",
        "typescript/no-non-null-assertion": "off",
        "typescript/no-unsafe-assignment": "off",
        "typescript/no-unsafe-member-access": "off",
        "typescript/no-unsafe-type-assertion": "off",
        "typescript/require-await": "off",
        "unicorn/consistent-function-scoping": "off",
        "@tanstack/query/exhaustive-deps": "off",
        ...(vitest ? VITEST_RULES : {}),
        ...(bun && !vitest ? { "jest/prefer-to-be": "error" } : {}),
        ...(node ? NODE_TEST_RULES : {}),
        ...(testingLibrary ? TESTING_LIBRARY_RULES : {}),
      },
    },
  ];
  if (bun) {
    const bunTestFiles = options.bunTestFiles ?? DEFAULT_BUN_TEST_FILES;
    overrides.push({ files: [...bunTestFiles], plugins: ["jest"], rules: { ...vitestOff, "jest/prefer-to-be": "error" } });
  }
  if (playwright) {
    // Playwright's rules recognize a global `expect`, so they run on Playwright files only.
    const playwrightTestFiles = options.playwrightTestFiles ?? DEFAULT_PLAYWRIGHT_TEST_FILES;
    overrides.push({ files: [...playwrightTestFiles], rules: { ...vitestOff, ...PLAYWRIGHT_RULES } });
  }
  overrides.push(
    { files: SHADCN_EXEMPT_FILES, rules: { "@sarj/prefer-shadcn-primitives": "off" } },
    { files: NEXT_APP_FILES, rules: { "oxc/no-barrel-file": "warn" } },
  );
  if (syntaxOnlyConfigFiles.length > 0) {
    // Last, so no file-specific override restores a type-aware rule.
    overrides.push({
      files: [...syntaxOnlyConfigFiles],
      rules: {
        ...Object.fromEntries(TYPE_AWARE_RULES.map((rule) => [rule, "off"])),
        "no-implied-eval": "error",
        "no-new-func": "error",
      },
    });
  }

  return defineConfig({
    plugins: ["eslint", "typescript", "unicorn", "react", "import", "promise", "oxc", "vitest"],
    jsPlugins: [
      { name: "@sarj", specifier: "@sarj/eslint-plugin" },
      { name: "eslint-js", specifier: "oxlint-plugin-eslint" },
      { name: "unicorn-js", specifier: "@sarj/eslint-plugin/unicorn" },
      { name: "jsdoc-js", specifier: "@sarj/eslint-plugin/jsdoc" },
      { name: "react-js", specifier: "@sarj/eslint-plugin/react" },
      { name: "regexp", specifier: "@sarj/eslint-plugin/regexp" },
      { name: "security", specifier: "@sarj/eslint-plugin/security" },
      { name: "zod", specifier: "eslint-plugin-zod" },
      { name: "@tanstack/query", specifier: "@sarj/eslint-plugin/query" },
      { name: "@eslint-react", specifier: "@sarj/eslint-plugin/react-correctness" },
      { name: "effects", specifier: "@sarj/eslint-plugin/effects" },
      ...(node ? [{ name: "node-test", specifier: "@sarj/eslint-plugin/node-test" }] : []),
      ...(testingLibrary ? [{ name: "testing-library", specifier: "@sarj/eslint-plugin/testing-library" }] : []),
      ...(playwright ? [{ name: "playwright", specifier: "@sarj/eslint-plugin/playwright" }] : []),
    ],
    categories: { correctness: "off" },
    env: { builtin: true },
    // Oxlint has no React version detection; its React rules assume the latest version.
    // Oxlint reads `settings` only from the root config, so the entrypoint passes these through.
    settings: testingLibrary
      ? { "testing-library/custom-queries": "off", "testing-library/custom-renders": "off", "testing-library/utils-module": "off" }
      : {},
    options: { typeAware: true, typeCheck: true, denyWarnings: true, reportUnusedDisableDirectives: "error" },
    rules: RULES,
    overrides,
  });
}

export default createConfig();
