import { readdirSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import tseslint from "typescript-eslint";
import react from "eslint-plugin-react";
import { fixupPluginRules } from "@eslint/compat";
import reactHooks from "eslint-plugin-react-hooks";
import unicorn from "eslint-plugin-unicorn";
import eslintComments from "@eslint-community/eslint-plugin-eslint-comments";
import perfectionist from "eslint-plugin-perfectionist";
import promise from "eslint-plugin-promise";
import simpleImportSort from "eslint-plugin-simple-import-sort";
import betterTailwindcss from "eslint-plugin-better-tailwindcss";
import sarj from "@sarj/eslint-plugin";
import zod from "eslint-plugin-zod";

const CONFIG_DIRECTORY = dirname(fileURLToPath(import.meta.url));
const TYPE_PROJECT_FILES = new Set(["tsconfig.json", "jsconfig.json"]);
const TYPE_PROJECT_SEARCH_DEPTH = 8;
const TYPE_PROJECT_SEARCH_LIMIT = 2_000;
const TYPE_PROJECT_SKIPPED_DIRECTORIES = new Set([
  ".git",
  ".next",
  ".turbo",
  "build",
  "coverage",
  "dist",
  "lib",
  "node_modules",
  "vendor",
]);

/**
 * Find a root or nested workspace type project without crawling dependencies.
 *
 * A direct `existsSync(root/tsconfig.json)` check silently disabled every typed
 * rule in monorepos whose configs live under `apps/*` or `packages/*`. Keep the
 * search bounded so config loading has deterministic cost even in huge repos.
 */
const hasTypeProject = (root) => {
  const pending = [[root, 0]];
  let inspected = 0;

  while (pending.length > 0 && inspected < TYPE_PROJECT_SEARCH_LIMIT) {
    const [directory, depth] = pending.shift();
    inspected += 1;
    let entries;
    try {
      entries = readdirSync(directory, { withFileTypes: true });
    } catch {
      continue;
    }
    if (entries.some((entry) => entry.isFile() && TYPE_PROJECT_FILES.has(entry.name))) return true;
    if (depth >= TYPE_PROJECT_SEARCH_DEPTH) continue;
    for (const entry of entries) {
      if (
        entry.isDirectory() &&
        !entry.name.startsWith(".") &&
        !TYPE_PROJECT_SKIPPED_DIRECTORIES.has(entry.name)
      ) {
        pending.push([join(directory, entry.name), depth + 1]);
      }
    }
  }
  return false;
};

const normalizeRoot = (root) => {
  const value = root instanceof URL ? fileURLToPath(root) : root;
  return isAbsolute(value) ? value : resolve(value);
};
const UNTYPED_RULE_OVERRIDES = Object.fromEntries(
  Object.entries(tseslint.plugin.rules)
    .filter(([, rule]) => rule.meta?.docs?.requiresTypeChecking === true)
    .map(([name]) => [`@typescript-eslint/${name}`, "off"]),
);
const DEFAULT_SYNTAX_ONLY_CONFIG_FILES = [
  "**/vite.config.ts",
  "**/.dependency-cruiser.{js,cjs,mjs,ts,cts,mts}",
  "**/eslint.config*.{js,cjs,mjs,ts,cts,mts}",
];

// Unicorn ships a broad rule set. The enabled subset below was selected by
// evaluating each non-deprecated rule for correctness, runtime compatibility,
// overlap with existing authorities, and whether its fix preserves semantics.
// Correctness rules also act as ratchets against newly introduced defects.
//
// Rules are declared as two objects rather than inline so the version guard
// below can check them, and so the two intents stay separable.
//
// REQUIRES eslint-plugin-unicorn >= 72 (and therefore eslint >= 10.4). 121 of
// these rules do not exist in unicorn 64 and 96 do not exist in 65; on an older
// plugin ESLint would emit "Definition for rule ... was not found" once per rule
// per file. The guard below turns that into one actionable line.

// Correctness. These catch BUGS, not style: useless/unnecessary constructs that
// are almost always a symptom of a wrong edit (`no-unnecessary-await`,
// `no-useless-fallback-in-spread`), calls that silently do nothing
// (`no-single-promise-in-promise-methods`, `no-invalid-fetch-options`), and
// footguns with real production failure modes (`no-array-fill-with-reference-type`,
// `no-unsafe-string-replacement`).
//
// DOM-family entries are included UNSCOPED on purpose. They are receiver-matched
// — they only fire on `document.*`, an `Element`, or an event API — so they are
// inert in a Node package and cost nothing there. Scoping them to `**/*.tsx`
// would have been worse than useless: measured, DOM code lives in plain `.ts`
// hooks and utility modules too, so a `.tsx` glob silently drops the findings.
// The DOM *modernisation* rules (prefer-query-selector, prefer-dom-node-append,
// dom-node-dataset, …) are rejected instead — see the rejection list below.
const UNICORN_CORRECTNESS_RULES = {
  "unicorn/class-reference-in-static-methods": "error",
  "unicorn/consistent-assert": "error",
  "unicorn/consistent-date-clone": "error",
  "unicorn/consistent-empty-array-spread": "error",
  "unicorn/consistent-json-file-read": "error",
  "unicorn/error-message": "error",
  "unicorn/explicit-timer-delay": "error",
  "unicorn/new-for-builtins": "error",
  "unicorn/no-accessor-recursion": "error",
  "unicorn/no-accidental-bitwise-operator": "error",
  "unicorn/no-array-concat-in-loop": "error",
  "unicorn/no-array-fill-with-reference-type": "error",
  "unicorn/no-array-from-fill": "error",
  "unicorn/no-array-method-this-argument": "error",
  "unicorn/no-array-sort-for-min-max": "error",
  "unicorn/no-async-promise-finally": "error",
  "unicorn/no-await-in-promise-methods": "error",
  "unicorn/no-blob-to-file": "error",
  "unicorn/no-boolean-sort-comparator": "error",
  "unicorn/no-canvas-to-image": "error",
  "unicorn/no-chained-comparison": "error",
  "unicorn/no-collection-bracket-access": "error",
  "unicorn/no-confusing-array-splice": "error",
  "unicorn/no-confusing-array-with": "error",
  "unicorn/no-constant-zero-expression": "error",
  "unicorn/no-document-cookie": "error",
  "unicorn/no-double-comparison": "error",
  "unicorn/no-duplicate-if-branches": "error",
  "unicorn/no-duplicate-logical-operands": "error",
  "unicorn/no-duplicate-loops": "error",
  "unicorn/no-duplicate-set-values": "error",
  "unicorn/no-empty-file": "error",
  "unicorn/no-error-property-assignment": "error",
  "unicorn/no-exports-in-scripts": "error",
  "unicorn/no-global-object-property-assignment": "error",
  "unicorn/no-immediate-mutation": "error",
  "unicorn/no-impossible-length-comparison": "error",
  "unicorn/no-incorrect-query-selector": "error",
  "unicorn/no-incorrect-template-string-interpolation": "error",
  "unicorn/no-instanceof-builtins": "error",
  "unicorn/no-invalid-argument-count": "error",
  "unicorn/no-invalid-character-comparison": "error",
  "unicorn/no-invalid-fetch-options": "error",
  "unicorn/no-invalid-file-input-accept": "error",
  "unicorn/no-invalid-remove-event-listener": "error",
  "unicorn/no-invalid-well-known-symbol-methods": "error",
  "unicorn/no-late-current-target-access": "error",
  "unicorn/no-late-event-control": "error",
  "unicorn/no-loop-iterable-mutation": "error",
  "unicorn/no-magic-array-flat-depth": "error",
  "unicorn/no-mismatched-map-key": "error",
  "unicorn/no-misrefactored-assignment": "error",
  "unicorn/no-missing-local-resource": "error",
  "unicorn/no-multiple-promise-resolver-calls": "error",
  "unicorn/no-negation-in-equality-check": "error",
  "unicorn/no-new-array": "error",
  "unicorn/no-new-buffer": "error",
  "unicorn/no-nonstandard-builtin-properties": "error",
  "unicorn/no-object-methods-with-collections": "error",
  "unicorn/no-optional-chaining-on-undeclared-variable": "error",
  "unicorn/no-redundant-comparison": "error",
  "unicorn/no-return-array-push": "error",
  "unicorn/no-selector-as-dom-name": "error",
  "unicorn/no-shorthand-property-overrides": "error",
  "unicorn/no-single-promise-in-promise-methods": "error",
  "unicorn/no-subtraction-comparison": "error",
  // JSON Schema requires a `then` property. The syntax-only rule rejects that
  // standards-compliant data shape even when the key is computed.
  "unicorn/no-thenable": "off",
  "unicorn/no-this-assignment": "error",
  "unicorn/no-this-outside-of-class": "error",
  "unicorn/no-typeof-undefined": "error",
  "unicorn/no-uncalled-method": "error",
  "unicorn/no-undeclared-class-members": "error",
  "unicorn/no-unnecessary-array-flat-depth": "error",
  "unicorn/no-unnecessary-array-flat-map": "error",
  "unicorn/no-unnecessary-array-splice-count": "error",
  "unicorn/no-unnecessary-await": "error",
  "unicorn/no-unnecessary-boolean-comparison": "error",
  "unicorn/no-unnecessary-fetch-options": "error",
  "unicorn/no-unnecessary-global-this": "error",
  "unicorn/no-unnecessary-nested-ternary": "error",
  "unicorn/no-unnecessary-polyfills": "error",
  "unicorn/no-unnecessary-slice-end": "error",
  "unicorn/no-unnecessary-splice": "error",
  "unicorn/no-unnecessary-string-trim": "error",
  "unicorn/no-unsafe-buffer-conversion": "error",
  "unicorn/no-unsafe-dom-html": "error",
  "unicorn/no-unsafe-promise-all-settled-values": "error",
  "unicorn/no-unsafe-property-key": "error",
  "unicorn/no-unsafe-string-replacement": "error",
  "unicorn/no-unused-array-method-return": "error",
  "unicorn/no-useless-boolean-cast": "error",
  "unicorn/no-useless-collection-argument": "error",
  "unicorn/no-useless-compound-assignment": "error",
  "unicorn/no-useless-concat": "error",
  "unicorn/no-useless-continue": "error",
  "unicorn/no-useless-delete-check": "error",
  "unicorn/no-useless-else": "error",
  "unicorn/no-useless-error-capture-stack-trace": "error",
  "unicorn/no-useless-fallback-in-spread": "error",
  "unicorn/no-useless-iterator-to-array": "error",
  "unicorn/no-useless-length-check": "error",
  "unicorn/no-useless-logical-operand": "error",
  "unicorn/no-useless-override": "error",
  "unicorn/no-useless-promise-resolve-reject": "error",
  "unicorn/no-useless-re-export": "error",
  "unicorn/no-useless-recursion": "error",
  "unicorn/no-useless-spread": "error",
  // Explicit union cases are required by switch-exhaustiveness-check even when
  // they share the default branch behavior.
  "unicorn/no-useless-switch-case": "off",
  "unicorn/no-xor-as-exponentiation": "error",
  "unicorn/prefer-add-event-listener": "error",
  "unicorn/prefer-add-event-listener-options": "error",
  "unicorn/prefer-keyboard-event-key": "error",
  "unicorn/require-array-join-separator": "error",
  "unicorn/require-css-escape": "error",
  "unicorn/require-module-attributes": "error",
  "unicorn/require-module-specifiers": "error",
  "unicorn/require-number-to-fixed-digits-argument": "error",
  "unicorn/require-passive-events": "error",
  "unicorn/require-post-message-target-origin": "error",
  "unicorn/require-proxy-trap-boolean-return": "error",
  "unicorn/text-encoding-identifier-case": "error",
};

// Modernisation. Enabled only where the fix is mechanical (autofix or a
// one-line suggestion), semantics-preserving, and reaches a platform API that
// exists on the declared floor (Node 22 / `lib: ES2025`). For example,
// `prefer-error-is-error` remains disabled because `Error.isError` is absent
// on Node 22 and its autofix would turn valid checks into runtime TypeErrors.
//
// Two of these need `lib` >= ES2025 in the CONSUMER to typecheck after the fix
// (`prefer-iterator-to-array` -> `Iterator#toArray`, `prefer-set-methods` ->
// `Set#union` and friends). Both are ES2025 library types available in TS today;
// a consumer still on `lib: ES2024` bumps `lib`, it does not bump its runtime.
const UNICORN_MODERNISATION_RULES = {
  "unicorn/no-array-reverse": "error",
  "unicorn/no-array-sort": "error",
  "unicorn/no-for-loop": "error",
  "unicorn/prefer-abort-signal-any": "error",
  "unicorn/prefer-abort-signal-timeout": "error",
  "unicorn/prefer-aggregate-error": "error",
  "unicorn/prefer-array-flat": "error",
  "unicorn/prefer-array-flat-map": "error",
  "unicorn/prefer-array-from-async": "error",
  "unicorn/prefer-array-from-map": "error",
  "unicorn/prefer-array-from-range": "error",
  "unicorn/prefer-array-index-of": "error",
  "unicorn/prefer-array-iterable-methods": "error",
  "unicorn/prefer-array-last-methods": "error",
  "unicorn/prefer-array-slice": "error",
  "unicorn/prefer-array-some": "error",
  "unicorn/prefer-at": "error",
  "unicorn/prefer-bigint-literals": "error",
  "unicorn/prefer-blob-reading-methods": "error",
  "unicorn/prefer-class-fields": "error",
  "unicorn/prefer-code-point": "error",
  "unicorn/prefer-date-now": "error",
  "unicorn/prefer-default-parameters": "error",
  "unicorn/prefer-direct-iteration": "error",
  "unicorn/prefer-event-target": "error",
  "unicorn/prefer-export-from": "error",
  "unicorn/prefer-flat-math-min-max": "error",
  "unicorn/prefer-global-number-constants": "error",
  "unicorn/prefer-group-by": "error",
  "unicorn/prefer-has-check": "error",
  "unicorn/prefer-https": "error",
  "unicorn/prefer-identifier-import-export-specifiers": "error",
  "unicorn/prefer-import-meta-properties": "error",
  "unicorn/prefer-iterable-in-constructor": "error",
  "unicorn/prefer-iterator-concat": "error",
  "unicorn/prefer-iterator-to-array": "error",
  "unicorn/prefer-map-from-entries": "error",
  "unicorn/prefer-math-abs": "error",
  "unicorn/prefer-math-constants": "error",
  "unicorn/prefer-math-min-max": "error",
  "unicorn/prefer-math-trunc": "error",
  "unicorn/prefer-modern-math-apis": "error",
  "unicorn/prefer-module": "error",
  "unicorn/prefer-native-coercion-functions": "error",
  "unicorn/prefer-negative-index": "error",
  "unicorn/prefer-number-is-safe-integer": "error",
  "unicorn/prefer-number-properties": "error",
  "unicorn/prefer-object-define-properties": "error",
  "unicorn/prefer-object-destructuring-defaults": "error",
  "unicorn/prefer-object-from-entries": "error",
  "unicorn/prefer-object-iterable-methods": "error",
  "unicorn/prefer-optional-catch-binding": "error",
  "unicorn/prefer-promise-with-resolvers": "error",
  "unicorn/prefer-queue-microtask": "error",
  "unicorn/prefer-regexp-test": "error",
  "unicorn/prefer-response-static-json": "error",
  "unicorn/prefer-set-has": "error",
  "unicorn/prefer-set-methods": "error",
  "unicorn/prefer-set-size": "error",
  "unicorn/prefer-simple-sort-comparator": "error",
  "unicorn/prefer-simplified-conditions": "error",
  "unicorn/prefer-single-array-predicate": "error",
  "unicorn/prefer-single-replace": "error",
  "unicorn/prefer-split-limit": "error",
  "unicorn/prefer-spread": "error",
  "unicorn/prefer-string-match-all": "error",
  "unicorn/prefer-string-pad-start-end": "error",
  "unicorn/prefer-string-raw": "error",
  "unicorn/prefer-string-repeat": "error",
  "unicorn/prefer-string-slice": "error",
  "unicorn/prefer-string-trim-start-end": "error",
  "unicorn/prefer-then-catch": "error",
  "unicorn/prefer-type-error": "error",
  "unicorn/prefer-unary-minus": "error",
  "unicorn/prefer-unicode-code-point-escapes": "error",
  "unicorn/prefer-url-can-parse": "error",
  "unicorn/prefer-url-search-parameters": "error",
  "unicorn/prefer-while-loop-condition": "error",
};

// One actionable line instead of N x M "Definition for rule ... was not found".
// Self-maintaining: it re-derives the required names from the objects above, so
// adding a rule that a pinned consumer's plugin lacks fails loudly at config
// load rather than silently linting nothing.
const missingUnicornRules = [
  ...Object.keys(UNICORN_CORRECTNESS_RULES),
  ...Object.keys(UNICORN_MODERNISATION_RULES),
]
  .map((key) => key.slice("unicorn/".length))
  .filter((name) => !(name in unicorn.rules));

if (missingUnicornRules.length > 0) {
  throw new Error(
    `sarj-standards: ${String(missingUnicornRules.length)} rule(s) this config enables do not exist ` +
      `in the installed eslint-plugin-unicorn (${missingUnicornRules.slice(0, 5).join(", ")}). ` +
      `Either the plugin is older than the required >= 72 (which also needs eslint >= 10.4), ` +
      `or a rule name in this config is a typo or was renamed upstream.`,
  );
}

// Rules deliberately not enabled are grouped by durable reason:
//
// 1. APIs unavailable on Node 22 or `lib: ES2025`, including Error.isError,
//    Temporal, newer Uint8Array helpers, RegExp.escape, Promise.try, and explicit
//    resource management. Autofixes must not produce unsupported runtime calls.
//
// 2. Duplicate authorities already owned by typescript-eslint, eslint-comments,
//    perfectionist, or a narrower Sarj rule. One concern should yield one
//    diagnostic, and enabled rules must not prescribe contradictory rewrites.
//
// 3. Naming, null, formatting, and readability preferences that create broad
//    churn without establishing correctness. Prettier owns formatting, while
//    domain models retain authority over names, nullable values, and control flow.
//
// 4. Rules whose suggestions can change short-circuiting, TypeScript narrowing,
//    async error boundaries, memoization, or other observable behavior. These
//    require human design review rather than a shared autofix.
//
// 5. Rules that need project-specific vocabulary, entrypoint, or TODO policy.
//    Shared configuration cannot infer those boundaries safely.
//
// 6. DOM modernisation rules. Direct DOM access in component applications is an
//    intentional escape hatch; DOM correctness rules remain enabled above.
//
// 7. Rules deprecated by Unicorn, plus CSS-language rules that cannot run in a
//    JavaScript configuration.

// eslint-plugin-react 7 still uses APIs removed by ESLint 10. ESLint's official
// compatibility layer restores those APIs, keeping every React rule active
// instead of silently weakening the strict configuration on newer ESLint.
const compatibleReact = fixupPluginRules(react);

// Build output is not authored code, and this config had NO `ignores` at all —
// the single string "ignores" in the whole file was a word in a comment. ESLint
// 9/10 ignore only `node_modules/` and `.git/` by default, so `eslint .` in an
// adopting repo lints its own compiled output at `error` severity.
//
// Generated output contains transformed syntax and duplicated source that the
// author cannot fix directly. Excluding it keeps diagnostics attached to the
// source or generator that owns the change.
//
// The Python CLI has skipped exactly these directories since it shipped
// (`SKIP_DIR_NAMES` in `sarj_python_lint/__main__.py`), so the two halves of the
// same standard disagreed; this closes that gap rather than inventing a policy.
//
// `lib/` is included deliberately and is the only entry that can shadow authored
// code. It is the conventional Babel/tsc output directory for a published
// package, which is where the 21,284 came from. A repo that keeps SOURCE in
// `lib/` re-enables it in its own `eslint.config.mjs` override block, which is
// what that block is for:
//     { ignores: ["!lib/**"] }
const BUILD_OUTPUT_IGNORES = [
  "**/dist/**",
  "**/build/**",
  "**/lib/**",
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
  "**/storybook-static/**",
  "**/__generated__/**",
  "**/generated/**",
  "**/eslint.config.js",
  "**/eslint.config.cjs",
  "**/eslint.config.mjs",
  "**/eslint.config.ts",
  "**/eslint.strict.mjs",
  "**/*.min.js",
  "**/*.min.mjs",
  "**/*.min.cjs",
];

/**
 * Build the config at call time, so an import cached from another working
 * directory cannot freeze type-aware linting off for the real project.
 *
 * @param {{ tsconfigRootDir?: string | URL, projectService?: boolean | object, syntaxOnlyConfigFiles?: string[] }} [options]
 * @returns {import("eslint").Linter.Config[]}
 */
export function createConfig(options = {}) {
  const explicitRoot = options.tsconfigRootDir === undefined
    ? undefined
    : normalizeRoot(options.tsconfigRootDir);
  const candidates = explicitRoot === undefined
    ? [CONFIG_DIRECTORY, process.cwd()].map(normalizeRoot)
    : [explicitRoot];
  const detectedRoot = candidates.find(hasTypeProject);
  const TYPE_PROJECT_ROOT = detectedRoot ?? candidates[0];
  const PROJECT_SERVICE = options.projectService ?? detectedRoot !== undefined;
  const HAS_TYPE_PROJECT = PROJECT_SERVICE !== false;
  const SYNTAX_ONLY_CONFIG_FILES = options.syntaxOnlyConfigFiles ?? DEFAULT_SYNTAX_ONLY_CONFIG_FILES;

  return [
  // A config entry carrying ONLY `ignores` is a global ignore — it must stay
  // first and must not grow a `files` key, or it silently degrades into a
  // per-file entry that ignores nothing.
  { ignores: BUILD_OUTPUT_IGNORES },

  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,

  {
    // Dead eslint-disable directives are an error (parity with ruff RUF100).
    linterOptions: {
      reportUnusedDisableDirectives: "error",
      reportUnusedInlineConfigs: "error",
    },
    plugins: {
      "@typescript-eslint": tseslint.plugin,
      react: compatibleReact,
      "react-hooks": reactHooks,
      unicorn,
      "@eslint-community/eslint-comments": eslintComments,
      perfectionist,
      promise,
      "simple-import-sort": simpleImportSort,
      "@sarj": sarj,
      zod,
    },
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        projectService: PROJECT_SERVICE,
        tsconfigRootDir: TYPE_PROJECT_ROOT,
        ecmaFeatures: { jsx: true },
      },
    },
    settings: { react: { version: "detect" } },
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-non-null-assertion": "error",
      "@typescript-eslint/no-deprecated": "error",
      "@typescript-eslint/only-throw-error": [
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
      // The upstream rule flags every nested then/catch/finally call, including
      // deliberate fire-and-forget work and synchronous framework callbacks.
      // The typed @sarj rule below owns only semantics-preserving async returns.
      "promise/prefer-await-to-then": "off",
      "@typescript-eslint/require-await": "error",
      // `isolatedDeclarations` requires annotations on exported values that
      // cannot be declaration-emitted in isolation, even when the initializer
      // looks inferable. The compiler owns that boundary.
      "@typescript-eslint/no-inferrable-types": "off",
      "@typescript-eslint/restrict-template-expressions": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
          ignoreRestSiblings: true,
        },
      ],
      "@typescript-eslint/consistent-indexed-object-style": ["error", "record"],
      "@typescript-eslint/consistent-type-imports": [
        "error",
        {
          prefer: "type-imports",
          fixStyle: "inline-type-imports",
        },
      ],
      "@typescript-eslint/switch-exhaustiveness-check": "error",
      "@typescript-eslint/consistent-type-assertions": [
        "error",
        {
          assertionStyle: "never",
        },
      ],
      "@typescript-eslint/naming-convention": [
        "error",
        {
          selector: "default",
          format: ["camelCase"],
          leadingUnderscore: "allow",
          trailingUnderscore: "allow",
          filter: {
            regex: "^(UNSAFE_|__)",
            match: false,
          },
        },
        {
          selector: "variable",
          format: ["camelCase", "UPPER_CASE", "PascalCase"],
          leadingUnderscore: "allow",
        },
        { selector: "typeLike", format: ["PascalCase"] },
        {
          selector: "import",
          format: ["camelCase", "PascalCase", "UPPER_CASE"],
        },
        { selector: "objectLiteralProperty", format: null },
        { selector: "typeProperty", format: null },
        {
          selector: "parameter",
          format: ["camelCase", "snake_case"],
          leadingUnderscore: "allow",
        },
      ],
      // Only accessibility bands are ordered. Field-vs-method and static-vs-
      // instance layout remain unconstrained, while public methods cannot be
      // buried below implementation-private methods. `@sarj/stepdown` then
      // orders sole-caller private helpers within the private band.
      "@typescript-eslint/member-ordering": [
        "error",
        {
          default: "never",
          interfaces: "never",
          typeLiterals: "never",
          classes: {
            memberTypes: [
              ["public-constructor", "public-accessor", "public-get", "public-set", "public-method", "public-static-method", "public-instance-method", "public-decorated-method"],
              ["protected-constructor", "protected-accessor", "protected-get", "protected-set", "protected-method", "protected-static-method", "protected-instance-method", "protected-decorated-method"],
              ["private-constructor", "private-accessor", "#private-accessor", "private-get", "#private-get", "private-set", "#private-set", "private-method", "private-static-method", "private-instance-method", "private-decorated-method", "#private-method"],
            ],
            order: "as-written",
          },
          classExpressions: {
            memberTypes: [
              ["public-constructor", "public-accessor", "public-get", "public-set", "public-method", "public-static-method", "public-instance-method", "public-decorated-method"],
              ["protected-constructor", "protected-accessor", "protected-get", "protected-set", "protected-method", "protected-static-method", "protected-instance-method", "protected-decorated-method"],
              ["private-constructor", "private-accessor", "#private-accessor", "private-get", "#private-get", "private-set", "#private-set", "private-method", "private-static-method", "private-instance-method", "private-decorated-method", "#private-method"],
            ],
            order: "as-written",
          },
        },
      ],

      // Additional type-aware strictness incorporated from a first-party base config.
      "@typescript-eslint/prefer-as-const": "error",
      "@typescript-eslint/no-unnecessary-condition": "error",
      "@typescript-eslint/prefer-nullish-coalescing": [
        "error",
        { ignorePrimitives: { number: true, string: true, boolean: true } },
      ],
      "@typescript-eslint/prefer-optional-chain": "error",
      // `require-await` rejects async functions without awaits, while this rule
      // requires `async` on functions that directly return a Promise. The two
      // rules deadlock on `() => Promise.resolve(value)`; require-await wins.
      "@typescript-eslint/promise-function-async": "off",
      "@typescript-eslint/no-confusing-void-expression": [
        "error",
        { ignoreArrowShorthand: true },
      ],
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
      "@typescript-eslint/consistent-type-exports": "error",
      "@typescript-eslint/array-type": "error",
      // `no-else-return` used to sit here. It is gone because
      // `unicorn/no-useless-else` (enabled below) is a strict superset: it flags
      // `else` after `throw`, `break` and `continue` as well as after `return`.
      // Keeping both would double-report the return case, which this config
      // treats as a bug: one diagnostic per concern.

      "react/jsx-no-leaked-render": [
        "error",
        { validStrategies: ["ternary", "coerce"] },
      ],
      "react/no-unstable-nested-components": "error",
      "react-hooks/exhaustive-deps": "error",
      "react-hooks/rules-of-hooks": "error",
      // Runtime correctness rules that do not require enabling React Compiler.
      "react-hooks/error-boundaries": "error",
      "react-hooks/globals": "error",
      "react-hooks/immutability": "error",
      "react-hooks/purity": "error",
      "react-hooks/refs": "error",
      "react-hooks/set-state-in-render": "error",
      // These rules cannot distinguish a raw inline style from the CSS custom
      // properties their own message recommends for dynamic utility values.
      // Semantic-color and design-system rules remain the style authorities.
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
      "react/no-invalid-html-attribute": "error",
      "react/style-prop-object": "error",
      "react/button-has-type": "error",
      "react/jsx-boolean-value": ["error", "never"],

      "unicorn/consistent-function-scoping": "error",
      // Kebab-case filenames. unicorn handles most framework shapes for free:
      // brackets and parens are "ignored characters" so `[id].tsx`,
      // `[...slug].tsx` and `(marketing)/` only have their inner word checked,
      // and `multipleFileExtensions` (default true) checks only the segment
      // before the FIRST dot, so `vite.config.ts`, `foo.test.ts` and
      // `app.module.css.ts` all pass on the stem alone.
      //
      // Framework-reserved names, config files, declarations, and barrel files
      // already satisfy the stem check or are covered by the explicit exceptions.
      //
      // The `ignore` list below is therefore short and each entry is earned:
      //   - `^__root\.`   TanStack Router's root route (a rename breaks routing)
      //   - `^_`          TanStack `_layout` / pathless routes, and this repo's
      //                   own `_paths.ts` / `_comments.ts` private helpers
      //   - `^\$`         TanStack dynamic segments, e.g. `$benchmarkId.tsx`
      //   - `^\+`         Expo Router specials, e.g. `+not-found.tsx`
      //   - `\.gen\.`     generated output — the generator owns the name, so a
      //                   rename is undone on the next codegen run
      // `\.d\.ts$` is deliberately DROPPED: it was redundant (the stem check
      // already ignores the `.d` middle segment) and over-broad — it let
      // `apiTypes.d.ts` through, which is a genuine violation.
      //
      // `checkDirectories` is deliberately omitted because route-directory
      // names are often public URLs; renaming one can change user-visible behavior.
      "unicorn/filename-case": [
        "error",
        {
          cases: { kebabCase: true },
          ignore: [
            String.raw`^__root\.`,
            String.raw`^_`,
            String.raw`^\$`,
            String.raw`^\+`,
            String.raw`\.gen\.`,
          ],
        },
      ],
      "unicorn/prefer-switch": "error",
      // Its `() => undefined` fix produces `() => {}`, which no-empty-function
      // rejects. Explicit undefined is the single authority for no-op arrows.
      "unicorn/no-useless-undefined": "off",
      "unicorn/prefer-node-protocol": "error",
      "unicorn/prefer-string-replace-all": "error",
      "unicorn/prefer-top-level-await": "error",
      "unicorn/no-await-expression-member": "error",
      "unicorn/prefer-structured-clone": "error",
      "unicorn/prefer-logical-operator-over-ternary": "error",
      "unicorn/relative-url-style": ["error", "never"],
      "unicorn/throw-new-error": "error",

      // The unicorn 72 expansion, declared and explained above the config.
      ...UNICORN_CORRECTNESS_RULES,
      ...UNICORN_MODERNISATION_RULES,

      "zod/prefer-enum-over-literal-union": "error",
      // A type hand-written beside the Zod schema it restates drifts when the
      // schema changes. Requiring an identical shape keeps the diagnostic tied
      // to structural evidence instead of name correlation.
      "@sarj/prefer-zod-infer": "error",

      // Maintained upstream rules own these concerns instead of local copies.
      // `.nullable().optional()` is exactly `.nullish()`, so prefer-nullish
      // provides a semantics-preserving autofix. `z.any()` leaks `any` through
      // inference where no-explicit-any cannot see it; `z.unknown()` accepts the
      // same inputs while requiring explicit narrowing.
      "zod/prefer-nullish": "error",
      "zod/no-any-schema": "error",

      // Deterministic ordering (incorporated from a first-party config).
      // simple-import-sort owns import/export ordering
      // (chosen over eslint-plugin-import to avoid Next.js resolver conflicts).
      // Object insertion order is observable through Object.keys/entries and
      // is commonly used for UI presentation. Sorting can silently change
      // behavior, so semantic order remains authoritative.
      "perfectionist/sort-objects": "off",
      "perfectionist/sort-interfaces": "error",
      // Alphabetical class sorting contradicts both accessibility bands and
      // caller-before-helper stepdown order. The two rules above own classes.
      "perfectionist/sort-classes": "off",
      "perfectionist/sort-jsx-props": "error",
      "perfectionist/sort-union-types": "error",
      // The rule skips imports instead of treating them as partitions, so its
      // fixer can move declarations across imports and directly violate
      // `@sarj/enforce-file-structure`. Keep imports-first as the authority.
      "perfectionist/sort-modules": "off",
      "simple-import-sort/imports": "error",
      "simple-import-sort/exports": "error",

      // Upstream rules require a description on eslint-disable and
      // @ts-expect-error directives. @sarj/no-vague-suppression-description
      // separately owns descriptions that exist but do not explain why;
      // ban-ts-comment remains the sole owner of forbidden @ts-ignore usage.
      "@eslint-community/eslint-comments/require-description": [
        "error",
        { ignore: [] },
      ],
      // ...and a suppression must name the rule it suppresses. A bare
      // `/* eslint-disable */` at the top of a file silently switches off EVERY
      // rule for the whole file — including ones added later — which is the
      // file-level-suppression escape hatch flagged repeatedly in review.
      "@eslint-community/eslint-comments/no-unlimited-disable": "error",
      "@eslint-community/eslint-comments/disable-enable-pair": [
        "error",
        { allowWholeFile: false },
      ],
      "@eslint-community/eslint-comments/no-aggregating-enable": "error",
      "@eslint-community/eslint-comments/no-duplicate-disable": "error",
      "@eslint-community/eslint-comments/no-unused-enable": "error",
      "@eslint-community/eslint-comments/no-restricted-disable": [
        "error",
        "no-console",
        "react-hooks/exhaustive-deps",
        "@sarj/no-vague-suppression-description",
      ],

      // Dedup: TS-enum ban → @sarj/no-enum, oversized-try-block ban →
      // @sarj/no-fat-try-blocks, and process.env ban → @sarj/no-raw-env (all
      // added below). Only the selectors WITHOUT a @sarj equivalent stay here,
      // so each concern fires exactly one diagnostic.
      "no-restricted-syntax": [
        "error",
        {
          selector: "CallExpression[callee.property.name='forEach']",
          message: "Prefer a for-of loop over forEach.",
        },
        {
          selector: "TSModuleDeclaration[kind='namespace']",
          message: "Use ES modules instead of namespaces.",
        },
      ],
      "no-restricted-imports": [
        "error",
        {
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
        },
      ],

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

      // The COMPLETE @sarj/eslint-plugin strict ruleset at each rule's declared strict severity.
      //
      // No version pin and no per-rule notes: a hand-written "@2.7.0" claim went
      // stale twice, and a declared list of tier deviations outlived the last
      // deviation it described. Both are now assertions instead of prose —
      // packages/typescript/tests/strict-config-sync.test.ts fails if this block
      // omits a shipped rule, names one that does not exist, or sets a tier the
      // plugin's own `configs.strict` does not. Each rule's measurements live in
      // the paired tests, which its `meta.docs.url` points at.
      //
      "@sarj/zod-naming-convention": "error",
      "@sarj/require-assert-never": "error",
      "@sarj/require-static-next-matcher": "error",
      "@sarj/require-zod-form-validation": "error",
      "@sarj/prefer-schema-for-api-payload": "error",
      "@sarj/no-client-side-data-fetching": "error",
      "@sarj/prefer-server-actions": "error",
      "@sarj/no-unnecessary-use-client": "error",
      "@sarj/no-enum": "error",
      "@sarj/no-raw-env": "error",
      "@sarj/no-sentinel-return-on-catch": "error",
      "@sarj/no-log-only-catch": "error",
      "@sarj/no-bare-return-from-test-catch": "warn",
      "@sarj/no-duplicate-lifecycle-refresh-listeners": "warn",
      "@sarj/no-router-refresh-polling": "warn",
      "@sarj/no-long-comment": "error",
      "@sarj/no-vague-suppression-description": "error",
      "@sarj/no-generic-single-export-module": "error",
      "@sarj/no-insecure-random-id": "error",
      "@sarj/no-json-stringify-error": "error",
      "@sarj/no-string-concat-in-loop": "error",
      "@sarj/prefer-discriminated-union": "error",
      "@sarj/no-comment-cruft": "error",
      "@sarj/no-fat-try-blocks": ["error", { max: 5 }],
      "@sarj/no-cors-wildcard-with-credentials": "error",
      "@sarj/no-secret-in-log": "error",
      "@sarj/no-hand-rolled-sleep": "error",
      "@sarj/no-hand-rolled-spinner": "error",
      "@sarj/prefer-input-group-search": "error",
      "@sarj/prefer-immutable-module-constant": "error",
      "@sarj/require-fetch-timeout": "error",
      "@sarj/no-silent-promise-catch": "error",
      "@sarj/enforce-file-structure": "error",
      "@sarj/prefer-semantic-colors": [
        "error",
        { requireSemanticTokens: true },
      ],
      "@sarj/prefer-constant-time-secret-compare": "error",
      "@sarj/no-dynamic-sql": "error",
      "@sarj/store-insert-requires-on-conflict": "error",
      "@sarj/stepdown": "error",
      "@sarj/no-offset-pagination": "error",
      "@sarj/no-select-star": "error",
      "@sarj/no-zod-native-enum": "error",
      "@sarj/no-impossible-zod-literal-bounds": "error",
      "@sarj/prefer-module-level-constant": "error",
      "@sarj/prefer-module-level-schema": "error",
      "@sarj/prefer-non-nullable-collection": "error",
      "@sarj/prefer-await-in-async-return": "error",
      "@sarj/no-sleep-in-test-body": "error",
      "@sarj/iac-source-coupled-test": "warn",
      "@sarj/repeated-static-call-cases": "warn",
      "@sarj/source-coupled-test": "warn",
      "@sarj/no-positional-tuple-return": "error",
      "@sarj/no-restated-comment": "error",
      "@sarj/no-restated-jsdoc": "error",
      "@sarj/no-trailing-value-narration": "error",
      "@sarj/no-declaration-comment-wall": "error",
      "@sarj/no-union-in-comment": "error",
      "@sarj/no-type-member-comment-wall": "error",
      "@sarj/no-repeated-string-literal": "error",
      "@sarj/no-tautological-expect": "error",
      "@sarj/no-typed-doc-sections": "error",
      "@sarj/require-port-for-service": "error",
      "@sarj/no-unsafe-mock-casting": "error",
      "@sarj/prefer-whole-object-assertion": "error",
      "@sarj/duplicate-test-body": "error",
      "@sarj/test-loops-over-literal-cases": "error",
      "@sarj/test-phase-label-comment": "warn",
      // Both architectural rules stay enabled in the shared baseline. The
      // fetch rule ships conservative client/service defaults; consumers can
      // replace its `allow` list. The storage rule is intentionally inert until
      // a consumer declares its stateless module paths, but keeping it present
      // guarantees that the canonical config never silently omits a shipped
      // custom rule:
      //   "@sarj/no-storage-in-stateless-modules": ["error", { modules: [...] }],
      //   "@sarj/no-raw-fetch-outside-clients": ["error", { allow: [...] }],
      ...(HAS_TYPE_PROJECT ? {} : UNTYPED_RULE_OVERRIDES),
    },
  },

  ...(SYNTAX_ONLY_CONFIG_FILES.length === 0
    ? []
    : [{
      // Project service rejects conventional tool configs outside a tsconfig.
      // Pass [] when the project owns them; name other exceptions explicitly.
      files: SYNTAX_ONLY_CONFIG_FILES,
      languageOptions: {
        parserOptions: {
          program: null,
          project: false,
          projectService: false,
        },
      },
      rules: UNTYPED_RULE_OVERRIDES,
    }]),

  {
    files: [
      "**/*.test.ts",
      "**/*.test.tsx",
      "**/test/**/*",
      "**/tests/**/*",
      "**/__tests__/**/*",
    ],
    rules: {
      // Test doubles and partial external payload fixtures intentionally cross
      // type boundaries. Production keeps every rule below at error; tests use
      // runtime assertions to verify the boundary instead of reconstructing an
      // entire third-party object graph solely to satisfy static analysis.
      "@typescript-eslint/consistent-type-assertions": "off",
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-type-assertion": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
      "@typescript-eslint/promise-function-async": "off",
      "@typescript-eslint/require-await": "off",
      "no-await-in-loop": "off",
      "unicorn/consistent-function-scoping": "off",
    },
  },

  {
    files: ["**/components/ui/**", "**/components/design-system/**"],
    rules: {
      "react/forbid-elements": "off",
      // Prevent design-system primitives from becoming implicit submit buttons.
      "react/button-has-type": "error",
    },
  },

  // better-tailwindcss: class-string hygiene for Tailwind repos. Include plain
  // JS/TS because class helpers and variant definitions commonly live there.
  // these three rules only inspect literal class strings, so non-Tailwind repos
  // simply see zero findings. Kept in its own block so the plugin is only wired
  // where it applies.
  {
    files: ["**/*.{js,jsx,ts,tsx}"],
    plugins: {
      "better-tailwindcss": betterTailwindcss,
    },
    rules: {
      "better-tailwindcss/no-conflicting-classes": "error",
      "better-tailwindcss/no-duplicate-classes": "error",
      "better-tailwindcss/no-deprecated-classes": "error",
      "better-tailwindcss/no-unnecessary-whitespace": "error",
      "better-tailwindcss/enforce-shorthand-classes": "error",
    },
  },
  // React component IDENTIFIERS must be PascalCase for JSX to distinguish them
  // from intrinsic elements. Filenames remain kebab-case under the base policy.
  {
    files: ["**/*.tsx"],
    rules: {
      // PascalCase function and variable names are the React component
      // convention. The base TypeScript policy remains camelCase-only; widen
      // it only for TSX instead of rejecting every valid component or assuming
      // a particular framework/compiler setup.
      "@typescript-eslint/naming-convention": [
        "error",
        {
          selector: "default",
          format: ["camelCase", "PascalCase"],
          leadingUnderscore: "allow",
          trailingUnderscore: "allow",
          filter: { regex: "^(UNSAFE_|__)", match: false },
        },
        {
          selector: "variable",
          format: ["camelCase", "UPPER_CASE", "PascalCase"],
          leadingUnderscore: "allow",
        },
        { selector: "typeLike", format: ["PascalCase"] },
        {
          selector: "import",
          format: ["camelCase", "PascalCase", "UPPER_CASE"],
        },
        { selector: "objectLiteralProperty", format: null },
        { selector: "typeProperty", format: null },
        {
          selector: "parameter",
          format: ["camelCase", "snake_case"],
          leadingUnderscore: "allow",
        },
      ],
    },
  },

  ];
}

const config = createConfig();
export default config;
