/**
 * @fileoverview no-raw-env — a raw `process.env` read is untyped and unvalidated, so a missing variable surfaces as `undefined` in business logic.
 *
 * Port of the 18.x `no-raw-env` rule. File gates and per-file state
 * move to `before()`; the matching is unchanged.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-raw-env.test.ts
 */

import { defineRule, type ESTree, type SourceCode } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isScriptFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

/** Build / test / tooling config: `vite.config.ts`, `vitest.config.mts`, `playwright.config.ts`. */
const CONFIG_FILE_RE = /(^|[\\/])[\w.-]+\.config\.[cm]?[jt]sx?$/;

/** Exempt only boundary-named modules that contain a validation marker. */
const ENV_BOUNDARY_FILE_RE =
  /(^|[\\/])(?:env|client-env|server-env|client-settings|server-settings)\.[cm]?[jt]sx?$/;

const PROCESS_MODULES: readonly string[] = ["node:process", "process"];
const PROCESS_IMPORT_SPECIFIERS: readonly string[] = ["ImportDefaultSpecifier", "ImportNamespaceSpecifier"];

// Build-time constants that bundlers (webpack/Vite) statically replace — exempt.
const BUILD_TIME_CONSTANTS: ReadonlySet<string> = new Set(["NODE_ENV", "MODE", "DEV", "PROD", "SSR"]);

const PLATFORM_MARKERS: ReadonlySet<string> = new Set(["NEXT_RUNTIME", "VERCEL", "VERCEL_ENV", "CI"]);

/** True for the `process.env` member node (dotted or as the base of `process.env[key]`). */
function isProcessEnv(node: ESTree.MemberExpression, sourceCode: SourceCode): boolean {
  const receiver = unwrapExpression(node.object);
  if (receiver.type !== "Identifier" || getPropertyName(node) !== "env") return false;
  const binding = findVariable(sourceCode.getScope(receiver), receiver.name);
  if (binding === null || binding.defs.length === 0) return receiver.name === "process";
  return binding.defs.every((definition) => {
    const parent = definition.parent;
    return definition.type === "ImportBinding" &&
      parent?.type === "ImportDeclaration" &&
      parent.importKind !== "type" &&
      PROCESS_MODULES.includes(parent.source.value) &&
      PROCESS_IMPORT_SPECIFIERS.includes(definition.node.type);
  });
}

/** True for the `import.meta.env` member node (dotted or as the base of `import.meta.env[key]`). */
function isImportMetaEnv(node: ESTree.MemberExpression): boolean {
  return (
    getPropertyName(node) === "env" &&
    node.object.type === "MetaProperty" &&
    node.object.meta.name === "import" &&
    node.object.property.name === "meta"
  );
}

/** Match named bundler constants and host-owned platform markers. */
function isExemptVariableAccess(node: ESTree.MemberExpression): boolean {
  const parent = parentOf(node);
  if (parent?.type !== "MemberExpression" || parent.object !== node) return false;
  const name = getPropertyName(parent);
  return name !== null && (BUILD_TIME_CONSTANTS.has(name) || PLATFORM_MARKERS.has(name));
}

/** Match assignment and deletion targets, which do not read configuration. */
function isWriteTarget(node: ESTree.MemberExpression): boolean {
  const direct = parentOf(node);
  const access = direct?.type === "MemberExpression" && direct.object === node ? direct : node;
  const parent = parentOf(access);
  if (parent?.type === "AssignmentExpression") {
    return parent.left === access;
  }
  if (parent?.type === "UnaryExpression") {
    return parent.operator === "delete";
  }
  return false;
}

/** Match whole-environment pass-through such as `{ ...process.env }`. */
function isWholeEnvSpread(node: ESTree.MemberExpression): boolean {
  const parent = parentOf(node);
  return parent?.type === "SpreadElement" && parent.argument === node;
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow direct `process.env` and `import.meta.env` reads outside validated boundaries.",
      url: docsUrl("no-raw-env"),
    },
    schema: [],
    messages: {
      noRawEnv:
        "Do not read raw environment values directly. Import the validated env module so values are typed and checked at startup.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let reads: ESTree.MemberExpression[] = [];
    let boundaryFile = false;
    let hasValidationCall = false;
    return {
      before() {
        const filename = context.filename;
        const file = { filename, cwd: context.cwd };
        if (isTestFile(file) || isScriptFile(file) || CONFIG_FILE_RE.test(filename)) {
          return false;
        }
        sourceCode = context.sourceCode;
        reads = [];
        boundaryFile = ENV_BOUNDARY_FILE_RE.test(filename);
        hasValidationCall = false;
        return undefined;
      },
      CallExpression(node: ESTree.CallExpression): void {
        if (!boundaryFile) return;
        const callee = node.callee;
        if (callee.type === "Identifier" && callee.name === "createEnv") {
          hasValidationCall = true;
        } else if (callee.type === "MemberExpression") {
          const calleeReceiver = unwrapExpression(callee.object);
          const name = getPropertyName(callee);
          if (name === "parse" || name === "safeParse" ||
            (name === "object" && calleeReceiver.type === "Identifier" && calleeReceiver.name === "z")) {
            hasValidationCall = true;
          }
        }
      },
      MemberExpression(node: ESTree.MemberExpression): void {
        if (
          (isProcessEnv(node, sourceCode) || isImportMetaEnv(node)) &&
          !isExemptVariableAccess(node) &&
          !isWriteTarget(node) &&
          !isWholeEnvSpread(node)
        ) {
          reads.push(node);
        }
      },
      "Program:exit"(): void {
        if (boundaryFile && hasValidationCall) return;
        for (const node of reads) context.report({ node, messageId: "noRawEnv" });
      },
    };
  },
});
