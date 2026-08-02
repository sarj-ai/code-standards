/**
 * @fileoverview no-raw-env — a raw `process.env` read is untyped and unvalidated, so a missing variable surfaces as `undefined` in business logic.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-raw-env.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
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

const ENV_VALIDATION_MARKER_RE =
  /\bcreateEnv\s*\(|\bz\.object\s*\(|\.(?:safeParse|parse)\s*\(/;

function isValidatedEnvBoundary(filename: string, sourceText: string): boolean {
  return (
    ENV_BOUNDARY_FILE_RE.test(filename.replaceAll("\\", "/")) &&
    ENV_VALIDATION_MARKER_RE.test(sourceText)
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

const PLATFORM_MARKERS: ReadonlySet<string> = new Set([
  "NEXT_RUNTIME",
  "VERCEL",
  "VERCEL_ENV",
  "CI",
]);

/**
 * True when `node` is the base of an exempt named access like
 * `process.env.NODE_ENV` or `process.env.VERCEL` — a bundler-replaced constant
 * or a platform-injected marker.
 */
function isExemptVariableAccess(node: TSESTree.MemberExpression): boolean {
  const parent = node.parent;
  return (
    parent.type === "MemberExpression" &&
    parent.object === node &&
    !parent.computed &&
    parent.property.type === "Identifier" &&
    (BUILD_TIME_CONSTANTS.has(parent.property.name) ||
      PLATFORM_MARKERS.has(parent.property.name))
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

export default createRule<Options, MessageIds>({
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
          !isExemptVariableAccess(node) &&
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
