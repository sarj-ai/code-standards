/**
 * @fileoverview no-raw-env — a raw `process.env` read is untyped and unvalidated, so a missing variable surfaces as `undefined` in business logic.
 *
 * Follow each boundary input to its parser. Raw aliases must not escape
 * alongside the shared parsed settings object.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-raw-env.test.ts
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isScriptFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

/** Build / test / tooling config: `vite.config.ts`, `vitest.config.mts`, `playwright.config.ts`. */
const CONFIG_FILE_RE = /(^|[\\/])[\w.-]+\.config\.[cm]?[jt]sx?$/;

/** Recognize validation boundaries; each raw read must still reach a parser. */
const ENV_BOUNDARY_FILE_RE =
  /(^|[\\/])(?:env|settings|client-env|server-env|client-settings|server-settings)\.[cm]?[jt]sx?$/;

const PROCESS_MODULES: readonly string[] = ["node:process", "process"];
const PROCESS_IMPORT_SPECIFIERS: readonly string[] = [
  "ImportDefaultSpecifier",
  "ImportNamespaceSpecifier",
];

// Build-time constants that bundlers (webpack/Vite) statically replace — exempt.
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

/** True for the `process.env` member node (dotted or as the base of `process.env[key]`). */
function isProcessEnv(node: ESTree.MemberExpression, sourceCode: SourceCode): boolean {
  const receiver = unwrapExpression(node.object);
  if (receiver.type !== "Identifier" || getPropertyName(node) !== "env") return false;
  const binding = findVariable(sourceCode.getScope(receiver), receiver.name);
  if (binding === null || binding.defs.length === 0) return receiver.name === "process";
  return binding.defs.every((definition) => {
    const parent = definition.parent;
    return (
      definition.type === "ImportBinding" &&
      parent?.type === "ImportDeclaration" &&
      parent.importKind !== "type" &&
      PROCESS_MODULES.includes(parent.source.value) &&
      PROCESS_IMPORT_SPECIFIERS.includes(definition.node.type)
    );
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

function reachesValidation(
  node: Node,
  sourceCode: SourceCode,
  seen: ReadonlySet<TsVariable> = new Set(),
  depth = 0,
  budget = { remaining: 512 },
): boolean {
  // Complex flows are deliberately unreported, rather than guessed invalid.
  if (depth >= 24 || budget.remaining-- <= 0) return true;
  const parent = parentOf(node);
  if (parent === null) return false;
  switch (parent.type) {
    case "CallExpression":
      return (
        parent.arguments.some((argument) => argument === node) &&
        (isValidationCall(parent) ||
          (isScalarCoercion(parent, sourceCode) &&
            reachesValidation(parent, sourceCode, seen, depth + 1, budget)))
      );
    case "VariableDeclarator":
      return parent.init === node && validatedAlias(parent, sourceCode, seen, depth, budget);
    case "MemberExpression":
      return (
        parent.object === node && reachesValidation(parent, sourceCode, seen, depth + 1, budget)
      );
    case "Property":
      return (
        parent.value === node &&
        parent.kind === "init" &&
        !parent.method &&
        reachesValidation(parent, sourceCode, seen, depth + 1, budget)
      );
    case "ObjectExpression":
    case "ArrayExpression":
    case "SpreadElement":
    case "LogicalExpression":
    case "BinaryExpression":
    case "ConditionalExpression":
    case "TemplateLiteral":
    case "TSAsExpression":
    case "TSNonNullExpression":
    case "TSSatisfiesExpression":
      return reachesValidation(parent, sourceCode, seen, depth + 1, budget);
    default:
      return false;
  }
}

/** A declaration elsewhere in a module does not validate this particular read. */
function isValidationCall(node: ESTree.CallExpression): boolean {
  const callee = unwrapExpression(node.callee);
  return callee.type === "Identifier"
    ? callee.name === "createEnv"
    : callee.type === "MemberExpression" &&
        ["parse", "safeParse"].includes(getPropertyName(callee) ?? "");
}

/** Keep raw input away from arbitrary effects before its validation call. */
function isScalarCoercion(node: ESTree.CallExpression, sourceCode: SourceCode): boolean {
  const callee = unwrapExpression(node.callee);
  if (
    callee.type !== "Identifier" ||
    !["Number", "String", "Boolean", "BigInt"].includes(callee.name) ||
    node.arguments.length !== 1
  )
    return false;
  const binding = findVariable(sourceCode.getScope(callee), callee.name);
  return binding === null || binding.defs.length === 0;
}

/** Follow a stable raw-input alias only when every use reaches validation. */
function validatedAlias(
  node: ESTree.VariableDeclarator,
  sourceCode: SourceCode,
  seen: ReadonlySet<TsVariable>,
  depth: number,
  budget: { remaining: number },
): boolean {
  const declaration = parentOf(node);
  if (
    node.id.type !== "Identifier" ||
    declaration?.type !== "VariableDeclaration" ||
    declaration.kind !== "const"
  )
    return false;
  if (parentOf(declaration)?.type === "ExportNamedDeclaration") return false;
  const variable = findVariable(sourceCode.getScope(node.id), node.id.name);
  if (
    variable === null ||
    seen.has(variable) ||
    variable.references.some((ref) => ref.isWrite() && ref.init !== true)
  )
    return false;
  const reads = variable.references.filter((ref) => ref.isRead());
  const next = new Set([...seen, variable]);
  if (reads.length > 128) return true;
  return (
    reads.length > 0 &&
    reads.every((ref) => reachesValidation(ref.identifier, sourceCode, next, depth + 1, budget))
  );
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
        "Read one shared settings object validated at startup with Zod (or the existing typed settings loader). Parse required environment values once at the boundary and inject or import the validated result.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let reads: ESTree.MemberExpression[] = [];
    let boundaryFile = false;
    return {
      before() {
        const filename = context.filename;
        const file = { filename, cwd: context.cwd };
        boundaryFile = ENV_BOUNDARY_FILE_RE.test(filename);
        if (
          isTestFile(file) ||
          (isScriptFile(file) && !boundaryFile) ||
          CONFIG_FILE_RE.test(filename)
        ) {
          return false;
        }
        sourceCode = context.sourceCode;
        reads = [];
        return undefined;
      },
      MemberExpression(node: ESTree.MemberExpression): void {
        if (
          (isProcessEnv(node, sourceCode) || isImportMetaEnv(node)) &&
          !isExemptVariableAccess(node) &&
          !isWriteTarget(node) &&
          !(isWholeEnvSpread(node) && !boundaryFile)
        ) {
          reads.push(node);
        }
      },
      "Program:exit"(): void {
        for (const node of reads) {
          if (!boundaryFile || !reachesValidation(node, sourceCode))
            context.report({ node, messageId: "noRawEnv" });
        }
      },
    };
  },
});
