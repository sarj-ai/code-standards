/**
 * @fileoverview Disallow direct `process.env` access. Force all env reads
 * through a Zod-validated env module so configuration is typed and validated
 * at startup.
 *
 * The rule is about READING A CONFIGURATION VALUE in application code, and a
 * sweep of 2,186 real TypeScript files (zod / TanStack Query / react-router /
 * swr / zustand) produced 143 hits of which ~90% were not that. Four exemptions,
 * each measured against that corpus:
 *
 *   - **Write target.** `process.env.X = "yes"` sets a variable for a child
 *     process; there is no value being read, so the validated-env module has
 *     nothing to say about it. 20 hits, e.g.
 *     react-router/packages/react-router-dev/vite/plugins/prerender.ts:250 and
 *     react-router/packages/react-router-dev/vite/plugin.ts:2451.
 *   - **Whole-environment pass-through.** `{ ...process.env, NO_COLOR: "1" }`
 *     forwards the inherited environment to a spawned process — again no
 *     configuration value is read. 9 hits, e.g.
 *     react-router/integration/helpers/create-fixture.ts:45.
 *   - **Test files** (shared `isTestFile`). A test that drives a CLI has to set
 *     and read the raw environment; there is no app env module in scope. 50
 *     hits, e.g.
 *     react-router/packages/create-react-router/__tests__/create-react-router-test.ts:1052.
 *   - **Scripts and build/test config** (shared `isScriptFile`, plus a
 *     `*.config.*` basename). A `vitest.config.mts` / `playwright.config.ts`
 *     configures the *build*, runs before the app exists, and cannot import the
 *     app's validated env. 47 hits, e.g. swr/test/e2e/playwright.config.ts:16
 *     and zod/scripts/check-versions.ts:5.
 *
 * What survives is the shape the rule was written for: application code reading
 * a deployment setting, e.g. zod/packages/docs/loaders/stars.ts:1
 * (`const GITHUB_TOKEN = process.env.GITHUB_TOKEN!`).
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isScriptFile, isTestFile } from "./_paths.js";

type MessageIds = "noRawEnv";
type Options = readonly [];

/** Build / test / tooling config: `vite.config.ts`, `vitest.config.mts`, `playwright.config.ts`. */
const CONFIG_FILE_RE = /(^|[\\/])[\w.-]+\.config\.[cm]?[jt]sx?$/;

/**
 * Modules that define the validated env boundary have to read raw env exactly
 * once before handing values to Zod. Keep this path-scoped so ordinary
 * `config.ts`/settings helpers still use the boundary instead of becoming one.
 */
const ENV_BOUNDARY_FILE_RE =
  /(^|[\\/])(?:env|client-env|server-env|client-settings|server-settings)\.[cm]?[jt]sx?$/;

function isValidatedEnvBoundary(filename: string, sourceText: string): boolean {
  return (
    ENV_BOUNDARY_FILE_RE.test(filename.replaceAll("\\", "/")) &&
    /\bz\.object\s*\(/.test(sourceText) &&
    /\.parse\s*\(/.test(sourceText)
  );
}

/** True for the `process.env` member node (dotted or as the base of `process.env[key]`). */
function isProcessEnv(node: TSESTree.MemberExpression): boolean {
  return (
    !node.computed &&
    node.object.type === "Identifier" &&
    node.object.name === "process" &&
    node.property.type === "Identifier" &&
    node.property.name === "env"
  );
}

/** True for the `import.meta.env` member node (dotted or as the base of `import.meta.env[key]`). */
function isImportMetaEnv(node: TSESTree.MemberExpression): boolean {
  return (
    !node.computed &&
    node.property.type === "Identifier" &&
    node.property.name === "env" &&
    node.object.type === "MetaProperty" &&
    node.object.meta.name === "import" &&
    node.object.property.name === "meta"
  );
}

// Build-time constants that bundlers (webpack/Vite) statically replace — there is
// no runtime env value to route through the validated layer, so they are exempt.
const BUILD_TIME_CONSTANTS: ReadonlySet<string> = new Set([
  "NODE_ENV",
  "MODE",
  "DEV",
  "PROD",
  "SSR",
]);

/** True when `node` is the base of a build-time-constant access like `process.env.NODE_ENV`. */
function isBuildTimeConstantAccess(node: TSESTree.MemberExpression): boolean {
  const parent = node.parent;
  return (
    parent.type === "MemberExpression" &&
    parent.object === node &&
    !parent.computed &&
    parent.property.type === "Identifier" &&
    BUILD_TIME_CONSTANTS.has(parent.property.name)
  );
}

/**
 * True when the env access is the TARGET of an assignment (`process.env.X = v`,
 * `process.env.X ??= v`, `delete process.env.X`) rather than a read. Writing a
 * variable for a child process reads no configuration value.
 */
function isWriteTarget(node: TSESTree.MemberExpression): boolean {
  const access = node.parent.type === "MemberExpression" && node.parent.object === node ? node.parent : node;
  const parent = access.parent;
  if (parent.type === "AssignmentExpression") {
    return parent.left === access;
  }
  if (parent.type === "UnaryExpression") {
    return parent.operator === "delete";
  }
  return false;
}

/**
 * True when the WHOLE environment is spread into an object literal —
 * `{ ...process.env, NO_COLOR: "1" }`. That forwards the inherited environment
 * to a spawned process; it is not a read of any particular setting.
 */
function isWholeEnvSpread(node: TSESTree.MemberExpression): boolean {
  const parent = node.parent;
  return parent.type === "SpreadElement" && parent.argument === node;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-raw-env",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow direct `process.env` access; use a Zod-validated env module instead.",
    },
    schema: [],
    messages: {
      noRawEnv:
        "Do not read from `process.env` directly. Import the Zod-validated env module instead so values are typed and validated at startup.",
    },
  },
  defaultOptions: [],
  create(context) {
    const filename = context.filename;
    if (
      isTestFile(filename) ||
      isScriptFile(filename) ||
      CONFIG_FILE_RE.test(filename.replaceAll("\\", "/")) ||
      isValidatedEnvBoundary(filename, context.sourceCode.text)
    ) {
      return {};
    }
    return {
      MemberExpression(node: TSESTree.MemberExpression): void {
        if (
          (isProcessEnv(node) || isImportMetaEnv(node)) &&
          !isBuildTimeConstantAccess(node) &&
          !isWriteTarget(node) &&
          !isWholeEnvSpread(node)
        ) {
          context.report({
            node,
            messageId: "noRawEnv",
          });
        }
      },
    };
  },
});
