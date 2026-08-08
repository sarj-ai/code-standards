/**
 * @fileoverview no-raw-env — a raw `process.env` read is untyped and unvalidated, so a missing variable surfaces as `undefined` in business logic.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-raw-env.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isScriptFile, isTestFile } from "./_paths.js";

type MessageIds = "noRawEnv";
type Options = readonly [];

export const noRawEnvDocumentation = {
  summary: "Disallow direct `process.env` and `import.meta.env` reads outside validated boundaries.",
  rationale: "Raw environment reads are untyped and defer invalid configuration failures until use.",
  remediation: "Validate environment values at startup and import the typed configuration object.",
  category: "correctness",
  limitations: ["Host markers, assignment targets, tests, scripts, build config, and validated boundaries are excluded."],
  examples: [
    { id: "validated-environment", title: "Read validated configuration", outcome: "no-match", files: [{ path: "src/database.ts", source: "import { env } from './env.js'; const url = env.DATABASE_URL;" }], focusPath: "src/database.ts", expectedCount: 0, public: true },
    { id: "raw-environment-read", title: "Do not read raw configuration", outcome: "match", files: [{ path: "src/database.ts", source: "const url = process.env.DATABASE_URL;" }], focusPath: "src/database.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

/** Build / test / tooling config: `vite.config.ts`, `vitest.config.mts`, `playwright.config.ts`. */
const CONFIG_FILE_RE = /(^|[\\/])[\w.-]+\.config\.[cm]?[jt]sx?$/;

/** Exempt only boundary-named modules that contain a validation marker. */
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

/** Match named bundler constants and host-owned platform markers. */
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

/** Match assignment and deletion targets, which do not read configuration. */
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

/** Match whole-environment pass-through such as `{ ...process.env }`. */
function isWholeEnvSpread(node: TSESTree.MemberExpression): boolean {
  const parent = node.parent;
  return parent.type === "SpreadElement" && parent.argument === node;
}

export default createRule<Options, MessageIds>({
  name: "no-raw-env",
  documentation: noRawEnvDocumentation,
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow direct `process.env` and `import.meta.env` reads outside validated boundaries.",
    },
    schema: [],
    messages: {
      noRawEnv:
        "Do not read raw environment values directly. Import the validated env module so values are typed and checked at startup.",
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
