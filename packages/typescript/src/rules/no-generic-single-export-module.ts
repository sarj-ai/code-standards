/**
 * @fileoverview no-generic-single-export-module — a generic module name hides the responsibility expressed by its sole runtime export.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-generic-single-export-module.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "genericSingleExport";
type Options = [];

const GENERIC_STEMS = new Set([
  "base", "common", "constant", "constants", "core", "enum", "enums", "helper", "helpers",
  "misc", "model", "models", "shared", "stuff", "type", "types", "util", "utils",
]);

// Frameworks and common inheritance layouts own these filenames; a rename can
// break discovery or erase the conventional "base implementation" signal.
const CONVENTIONAL_STEMS = new Set(["base", "models"]);
const CJS_OBJECT_EXPORT_METHODS = new Set(["assign", "defineProperty"]);

interface FileParts {
  readonly extension: string;
  readonly stem: string;
  readonly suffixes: string[];
}

function fileParts(filename: string): FileParts {
  const base = filename.replaceAll("\\", "/").split("/").at(-1) ?? "";
  const extension = base.match(/(\.[cm]?[jt]sx?)$/u)?.[1] ?? ".ts";
  const segments = base.slice(0, -extension.length).split(".");
  return {
    extension,
    stem: segments[0]?.toLowerCase() ?? "",
    suffixes: segments.slice(1),
  };
}

function declaredNames(declaration: TSESTree.NamedExportDeclarations): string[] {
  if ((declaration as { declare?: boolean }).declare === true) return [];
  if (
    declaration.type === AST_NODE_TYPES.FunctionDeclaration ||
    declaration.type === AST_NODE_TYPES.ClassDeclaration ||
    declaration.type === AST_NODE_TYPES.TSEnumDeclaration
  ) {
    if (declaration.type === AST_NODE_TYPES.TSEnumDeclaration && declaration.const) return [];
    return declaration.id === null ? [] : [declaration.id.name];
  }
  if (declaration.type === AST_NODE_TYPES.TSModuleDeclaration && declaration.id.type === AST_NODE_TYPES.Identifier) {
    return [declaration.id.name];
  }
  if (declaration.type !== AST_NODE_TYPES.VariableDeclaration) return [];
  return declaration.declarations.flatMap((item) =>
    item.id.type === AST_NODE_TYPES.Identifier ? [item.id.name] : [],
  );
}

interface RuntimeExports {
  readonly exports: Array<{ readonly key: string; readonly name: string; readonly node: TSESTree.Node }>;
  readonly ambiguous: boolean;
}

/** Local bindings which exist only in TypeScript's type namespace. */
function typeOnlyBindings(program: TSESTree.Program): ReadonlySet<string> {
  const names = new Set<string>();
  const runtimeNames = new Set<string>();
  for (const statement of program.body) {
    if (
      statement.type === AST_NODE_TYPES.TSInterfaceDeclaration ||
      statement.type === AST_NODE_TYPES.TSTypeAliasDeclaration
    ) {
      names.add(statement.id.name);
      continue;
    }
    if (statement.type === AST_NODE_TYPES.TSEnumDeclaration && statement.const) {
      names.add(statement.id.name);
      continue;
    }
    if (statement.type === AST_NODE_TYPES.ImportDeclaration) {
      for (const specifier of statement.specifiers) {
        if (
          statement.importKind === "type" ||
          (specifier.type === AST_NODE_TYPES.ImportSpecifier && specifier.importKind === "type")
        ) {
          names.add(specifier.local.name);
        } else {
          runtimeNames.add(specifier.local.name);
        }
      }
      continue;
    }
    const declaration = statement.type === AST_NODE_TYPES.ExportNamedDeclaration
      ? statement.declaration
      : statement;
    if (declaration !== null && "type" in declaration) {
      for (const name of declaredNames(declaration as TSESTree.NamedExportDeclarations)) {
        runtimeNames.add(name);
      }
    }
  }
  return new Set([...names].filter((name) => !runtimeNames.has(name)));
}

function runtimeExports(program: TSESTree.Program): RuntimeExports {
  const exports: Array<{ key: string; name: string; node: TSESTree.Node }> = [];
  const typeBindings = typeOnlyBindings(program);
  let ambiguous = false;
  for (const statement of program.body) {
    if (statement.type === AST_NODE_TYPES.ExportAllDeclaration) {
      if (statement.exportKind !== "type") ambiguous = true;
      continue;
    }
    if (statement.type === AST_NODE_TYPES.ExportDefaultDeclaration) {
      const declaration = statement.declaration;
      if (declaration.type === AST_NODE_TYPES.Identifier) exports.push({ key: "default", name: declaration.name, node: statement });
      else if (
        (declaration.type === AST_NODE_TYPES.FunctionDeclaration || declaration.type === AST_NODE_TYPES.ClassDeclaration) &&
        declaration.id !== null &&
        declaration.declare !== true
      ) exports.push({ key: "default", name: declaration.id.name, node: declaration });
      else if (
        declaration.type !== AST_NODE_TYPES.TSInterfaceDeclaration &&
        declaration.type !== AST_NODE_TYPES.TSTypeAliasDeclaration
      ) ambiguous = true;
      continue;
    }
    if (statement.type !== AST_NODE_TYPES.ExportNamedDeclaration || statement.exportKind === "type") continue;
    if (statement.source !== null) {
      if (statement.specifiers.some((specifier) => specifier.exportKind !== "type")) ambiguous = true;
      continue;
    }
    if (statement.declaration !== null) {
      const declaration = statement.declaration;
      exports.push(...declaredNames(declaration).map((name) => ({ key: name, name, node: declaration })));
    }
    for (const specifier of statement.specifiers) {
      if (specifier.exportKind === "type" || typeBindings.has(specifier.local.name)) continue;
      const exported = specifier.exported.type === AST_NODE_TYPES.Identifier ? specifier.exported.name : specifier.exported.value;
      const local = specifier.local.name;
      exports.push({ key: exported, name: exported === "default" ? local : exported, node: specifier });
    }
  }
  const unique = new Map(exports.map((entry) => [entry.key, entry]));
  return { exports: [...unique.values()], ambiguous };
}

function kebabCase(name: string): string {
  return name
    .replaceAll("OAuth", "Oauth")
    .replaceAll("GraphQL", "Graphql")
    .replaceAll("gRPC", "Grpc")
    .replaceAll(/([a-z\d])([A-Z])/gu, "$1-$2")
    .replaceAll(/([A-Z]+)([A-Z][a-z])/gu, "$1-$2")
    .replaceAll(/[_\s]+/gu, "-")
    .replaceAll(/-+/gu, "-")
    .replaceAll(/^-|-$/gu, "")
    .toLowerCase();
}

function isGlobalIdentifier(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  node: TSESTree.Identifier,
): boolean {
  return ASTUtils.findVariable(context.sourceCode.getScope(node), node.name) === null;
}

function isConventionalFrameworkUtility(filename: string, exported: string): boolean {
  const normalized = filename.replaceAll("\\", "/");
  return exported === "cn" && /(?:^|\/)lib\/utils\.[cm]?[jt]sx?$/u.test(normalized);
}

export default createRule<Options, MessageIds>({
  name: "no-generic-single-export-module",
  meta: {
    type: "suggestion",
    docs: { description: "Disallow generic module stems when one runtime export already names the responsibility." },
    schema: [],
    messages: {
      genericSingleExport:
        "Module stem `{{stem}}` is generic and its only runtime export is `{{exported}}`; rename the file to `{{expected}}`.",
    },
  },
  defaultOptions: [],
  create(context) {
    const file = fileParts(context.filename);
    const { stem } = file;
    if (
      !GENERIC_STEMS.has(stem) ||
      CONVENTIONAL_STEMS.has(stem) ||
      isTestFile(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.text)
    ) return {};
    let hasCommonJsExport = false;
    return {
      CallExpression(node): void {
        const first = node.arguments[0];
        if (
          first?.type === AST_NODE_TYPES.Identifier &&
          first.name === "exports" &&
          isGlobalIdentifier(context, first) &&
          node.callee.type === AST_NODE_TYPES.MemberExpression &&
          node.callee.object.type === AST_NODE_TYPES.Identifier &&
          node.callee.object.name === "Object" &&
          !node.callee.computed &&
          node.callee.property.type === AST_NODE_TYPES.Identifier &&
          CJS_OBJECT_EXPORT_METHODS.has(node.callee.property.name)
        ) hasCommonJsExport = true;
      },
      MemberExpression(node): void {
        if (
          node.object.type === AST_NODE_TYPES.Identifier &&
          node.object.name === "exports" &&
          isGlobalIdentifier(context, node.object)
        ) hasCommonJsExport = true;
        if (
          node.object.type === AST_NODE_TYPES.Identifier &&
          node.object.name === "module" &&
          isGlobalIdentifier(context, node.object) &&
          !node.computed &&
          node.property.type === AST_NODE_TYPES.Identifier &&
          node.property.name === "exports"
        ) hasCommonJsExport = true;
      },
      "Program:exit"(program): void {
        if (hasCommonJsExport) return;
        const exports = runtimeExports(program);
        if (exports.ambiguous || exports.exports.length !== 1) return;
        const onlyExport = exports.exports[0];
        if (onlyExport === undefined) return;
        const { name: exported, node } = onlyExport;
        if (isConventionalFrameworkUtility(context.filename, exported)) return;
        const expectedStem = kebabCase(exported);
        const suffixStem = file.suffixes.join("-").toLowerCase();
        const currentResponsibility = [stem, suffixStem].filter(Boolean).join("-");
        if (
          expectedStem === currentResponsibility ||
          GENERIC_STEMS.has(expectedStem) ||
          !/^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(expectedStem)
        ) return;
        const suffixTail = suffixStem === "" ? "" : `-${suffixStem}`;
        const renameStem = suffixTail !== "" && expectedStem.endsWith(suffixTail)
          ? expectedStem.slice(0, -suffixTail.length)
          : expectedStem;
        if (renameStem === "" || GENERIC_STEMS.has(renameStem)) return;
        const suffix = file.suffixes.map((part) => `.${part}`).join("");
        context.report({
          node,
          messageId: "genericSingleExport",
          data: { stem, exported, expected: `${renameStem}${suffix}${file.extension}` },
        });
      },
    };
  },
});
