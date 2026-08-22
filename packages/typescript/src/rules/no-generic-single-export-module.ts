/**
 * @fileoverview no-generic-single-export-module — a generic module name hides the responsibility expressed by its sole runtime export.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-generic-single-export-module.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "genericSingleExport";
type Options = [];

export const NO_GENERIC_SINGLE_EXPORT_MODULE_DOCUMENTATION = {
  summary: "Disallow generic module stems when one runtime export already names the responsibility.",
  rationale: "A generic filename hides the sole exported responsibility and makes navigation less descriptive.",
  remediation: "Choose a responsibility-bearing module name or colocate the export with its domain.",
  category: "maintainability",
  limitations: ["Only configured generic stems with exactly one public runtime export are reported."],
  examples: [
    { id: "responsibility-named-module", title: "Name the module after its export", outcome: "no-match", files: [{ path: "src/order-parser.ts", source: "export function parseOrder() { return {}; }" }], focusPath: "src/order-parser.ts", expectedCount: 0, public: true },
    { id: "generic-module-name", title: "Do not hide one export in a generic module", outcome: "match", files: [{ path: "src/utils.ts", source: "export function parseOrder() { return {}; }" }], focusPath: "src/utils.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const GENERIC_STEMS: ReadonlySet<string> = new Set([
  "common", "helper", "helpers", "misc", "shared", "stuff", "util", "utils",
]);
const CJS_OBJECT_EXPORT_METHODS: ReadonlySet<string> = new Set(["assign", "defineProperties", "defineProperty"]);

interface FileParts {
  readonly stem: string;
  readonly suffixes: string[];
}

function fileParts(filename: string): FileParts {
  const base = filename.replaceAll("\\", "/").split("/").at(-1) ?? "";
  const extension = base.match(/(\.[cm]?[jt]sx?)$/u)?.[1] ?? ".ts";
  const [stem = "", ...suffixes] = base.slice(0, -extension.length).split(".");
  return { stem, suffixes: suffixes.map((suffix) => suffix.toLowerCase()) };
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
      if (declaration.type === AST_NODE_TYPES.Identifier) {
        if (!typeBindings.has(declaration.name)) {
          exports.push({ key: "default", name: declaration.name, node: statement });
        }
      }
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

/** Local bindings which exist only in TypeScript's type namespace. */
function typeOnlyBindings(program: TSESTree.Program): ReadonlySet<string> {
  const names = new Set<string>();
  const runtimeNames = new Set<string>();
  for (const statement of program.body) {
    const declaration = statement.type === AST_NODE_TYPES.ExportNamedDeclaration
      ? statement.declaration
      : statement;
    if (
      declaration?.type === AST_NODE_TYPES.TSInterfaceDeclaration ||
      declaration?.type === AST_NODE_TYPES.TSTypeAliasDeclaration
    ) {
      names.add(declaration.id.name);
      continue;
    }
    if (declaration?.type === AST_NODE_TYPES.TSEnumDeclaration && declaration.const) {
      names.add(declaration.id.name);
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
    if (declaration?.type === AST_NODE_TYPES.TSDeclareFunction && declaration.id !== null) {
      names.add(declaration.id.name);
      continue;
    }
    if (declaration !== null && (declaration as { declare?: boolean }).declare === true) {
      if (
        (declaration.type === AST_NODE_TYPES.ClassDeclaration ||
          declaration.type === AST_NODE_TYPES.FunctionDeclaration ||
          declaration.type === AST_NODE_TYPES.TSEnumDeclaration ||
          declaration.type === AST_NODE_TYPES.TSModuleDeclaration) &&
        declaration.id !== null &&
        declaration.id.type === AST_NODE_TYPES.Identifier
      ) names.add(declaration.id.name);
      if (declaration.type === AST_NODE_TYPES.VariableDeclaration) {
        for (const item of declaration.declarations) {
          if (item.id.type === AST_NODE_TYPES.Identifier) names.add(item.id.name);
        }
      }
      continue;
    }
    if (declaration !== null && "type" in declaration) {
      for (const name of declaredNames(declaration as TSESTree.NamedExportDeclarations)) {
        runtimeNames.add(name);
      }
    }
  }
  return new Set([...names].filter((name) => !runtimeNames.has(name)));
}

function isGlobalIdentifier(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  node: TSESTree.Identifier,
): boolean {
  const variable = ASTUtils.findVariable(context.sourceCode.getScope(node), node.name);
  return variable === null || variable.defs.length === 0;
}

function isConventionalFrameworkUtility(filename: string, exported: string): boolean {
  const normalized = filename.replaceAll("\\", "/");
  return exported === "cn" && /(?:^|\/)lib\/utils\.[cm]?[jt]sx?$/u.test(normalized);
}

function memberPropertyName(node: TSESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier) return node.property.name;
  return node.computed && node.property.type === AST_NODE_TYPES.Literal && typeof node.property.value === "string"
    ? node.property.value
    : null;
}

export default createRule<Options, MessageIds>({
  name: "no-generic-single-export-module",
  documentation: NO_GENERIC_SINGLE_EXPORT_MODULE_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: "Disallow generic module stems when one runtime export already names the responsibility." },
    schema: [],
    messages: {
      genericSingleExport:
        "Module stem `{{stem}}` is generic and its only runtime export is `{{exported}}`; choose a responsibility-bearing module name or colocate the export with its domain.",
    },
  },
  defaultOptions: [],
  create(context) {
    const file = fileParts(context.filename);
    const { stem } = file;
    if (
      !GENERIC_STEMS.has(stem) ||
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
          isGlobalIdentifier(context, node.callee.object) &&
          memberPropertyName(node.callee) !== null &&
          CJS_OBJECT_EXPORT_METHODS.has(memberPropertyName(node.callee)!)
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
          memberPropertyName(node) === "exports"
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
        const exportedRole = exported.replaceAll(/[^a-z0-9]/giu, "").toLowerCase();
        const pathRole = [stem, ...file.suffixes].join("").replaceAll(/[^a-z0-9]/giu, "");
        if (exportedRole === pathRole && file.suffixes.length > 0) return;
        context.report({
          node,
          messageId: "genericSingleExport",
          data: { stem, exported },
        });
      },
    };
  },
});
