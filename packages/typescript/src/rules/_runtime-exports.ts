/** @fileoverview _runtime-exports — classify runtime exports conservatively for module naming rules. */
import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

export const GENERIC_MODULE_STEMS: ReadonlySet<string> = new Set([
  "common", "helper", "helpers", "misc", "shared", "stuff", "util", "utils",
]);
const CJS_OBJECT_EXPORT_METHODS: ReadonlySet<string> = new Set(["assign", "defineProperties", "defineProperty"]);

type Emission = "runtime" | "erased" | "unknown";
interface RuntimeExport {
  readonly key: string;
  readonly name: string;
  readonly node: TSESTree.Node;
}
interface RuntimeExports {
  readonly exports: readonly RuntimeExport[];
  readonly ambiguous: boolean;
}

/** Count public runtime keys, preserving unknowns instead of silently dropping them. */
export function runtimeExports(program: TSESTree.Program): RuntimeExports {
  const bindings = localBindings(program);
  const exports = new Map<string, RuntimeExport>();
  let ambiguous = false;
  function add(key: string, name: string, node: TSESTree.Node, emission: Emission): void {
    if (emission === "unknown") ambiguous = true;
    if (emission === "runtime") exports.set(key, { key, name, node });
  }
  function collectDefault(statement: TSESTree.ExportDefaultDeclaration): void {
    const declaration = statement.declaration;
    if (declaration.type === AST_NODE_TYPES.Identifier) {
      add("default", declaration.name, statement, bindings.get(declaration.name) ?? "unknown");
    } else if ("id" in declaration && declaration.id?.type === AST_NODE_TYPES.Identifier) {
      add("default", declaration.id.name, declaration, declarationEmission(declaration));
    } else ambiguous = true;
  }
  function collectNamed(statement: TSESTree.ExportNamedDeclaration): void {
    if (statement.exportKind === "type") return;
    if (statement.source !== null) {
      if (statement.specifiers.some((specifier) => specifier.exportKind !== "type")) ambiguous = true;
      return;
    }
    const declaration = statement.declaration;
    if (declaration !== null) {
      if (declaration.type === AST_NODE_TYPES.VariableDeclaration &&
        declaration.declarations.some((item) => item.id.type !== AST_NODE_TYPES.Identifier)) ambiguous = true;
      const names = declarationNames(declaration);
      if (names.length === 0 && declarationEmission(declaration) !== "erased") ambiguous = true;
      for (const name of names) add(name, name, declaration, bindings.get(name) ?? "unknown");
    }
    for (const specifier of statement.specifiers) {
      if (specifier.exportKind === "type") continue;
      const key = specifier.exported.type === AST_NODE_TYPES.Identifier ? specifier.exported.name : specifier.exported.value;
      const local = specifier.local.name;
      add(key, key === "default" ? local : key, specifier, bindings.get(local) ?? "unknown");
    }
  }
  for (const statement of program.body) {
    if (statement.type === AST_NODE_TYPES.ExportAllDeclaration && statement.exportKind !== "type") ambiguous = true;
    if (statement.type === AST_NODE_TYPES.TSExportAssignment) ambiguous = true;
    if (statement.type === AST_NODE_TYPES.ExportDefaultDeclaration) collectDefault(statement);
    if (statement.type === AST_NODE_TYPES.ExportNamedDeclaration) collectNamed(statement);
  }
  return { exports: [...exports.values()], ambiguous };
}

function localBindings(program: TSESTree.Program): ReadonlyMap<string, Emission> {
  const bindings = new Map<string, Emission>();
  function register(name: string, emission: Emission): void {
    const previous = bindings.get(name);
    if (previous === "runtime" || emission === "runtime") bindings.set(name, "runtime");
    else if (previous === "unknown" || emission === "unknown") bindings.set(name, "unknown");
    else bindings.set(name, "erased");
  }
  for (const statement of program.body) {
    if (statement.type === AST_NODE_TYPES.ImportDeclaration) {
      for (const specifier of statement.specifiers) {
        const typeOnly = statement.importKind === "type" ||
          (specifier.type === AST_NODE_TYPES.ImportSpecifier && specifier.importKind === "type");
        register(specifier.local.name, typeOnly ? "erased" : "unknown");
      }
      continue;
    }
    const declaration = statement.type === AST_NODE_TYPES.ExportNamedDeclaration ||
      statement.type === AST_NODE_TYPES.ExportDefaultDeclaration ? statement.declaration : statement;
    if (declaration === null) continue;
    for (const name of declarationNames(declaration)) register(name, declarationEmission(declaration));
  }
  return bindings;
}

function declarationNames(declaration: TSESTree.Node): string[] {
  if ("id" in declaration && declaration.id !== null) {
    let id: TSESTree.Node = declaration.id;
    while (id.type === AST_NODE_TYPES.TSQualifiedName) id = id.left;
    if (id.type === AST_NODE_TYPES.Identifier) return [id.name];
  }
  if (declaration.type !== AST_NODE_TYPES.VariableDeclaration) return [];
  return declaration.declarations.flatMap((item) => item.id.type === AST_NODE_TYPES.Identifier ? [item.id.name] : []);
}

function declarationEmission(declaration: TSESTree.Node): Emission {
  if ("declare" in declaration && declaration.declare === true) return "erased";
  switch (declaration.type) {
    case AST_NODE_TYPES.TSInterfaceDeclaration:
    case AST_NODE_TYPES.TSTypeAliasDeclaration:
    case AST_NODE_TYPES.TSDeclareFunction:
      return "erased";
    case AST_NODE_TYPES.ClassDeclaration:
    case AST_NODE_TYPES.FunctionDeclaration:
    case AST_NODE_TYPES.VariableDeclaration:
      return "runtime";
    case AST_NODE_TYPES.TSEnumDeclaration:
      return declaration.const ? "unknown" : "runtime";
    case AST_NODE_TYPES.TSModuleDeclaration:
      return namespaceEmission(declaration);
    default:
      return "unknown";
  }
}

function namespaceEmission(declaration: TSESTree.TSModuleDeclaration): Emission {
  const { body } = declaration;
  if (body === undefined) return "unknown";
  if (body.body.length === 0) return "unknown";
  let ambiguous = false;
  for (const statement of body.body) {
    if (statement.type === AST_NODE_TYPES.ExportNamedDeclaration && statement.exportKind === "type") continue;
    const inner = statement.type === AST_NODE_TYPES.ExportNamedDeclaration ? statement.declaration : statement;
    const emission = inner === null ? "unknown" : declarationEmission(inner);
    if (emission === "runtime") return "runtime";
    if (emission === "unknown") ambiguous = true;
  }
  return ambiguous ? "unknown" : "erased";
}

/** Scope-aware CommonJS detection shared by both rules; mixed surfaces remain unknown. */
export function isCommonJsExportReference(
  node: TSESTree.CallExpression | TSESTree.MemberExpression,
  sourceCode: Readonly<TSESLint.SourceCode>,
): boolean {
  function isGlobal(node: TSESTree.Identifier): boolean {
    const variable = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
    return variable === null || variable.defs.length === 0;
  }
  if (node.type === AST_NODE_TYPES.MemberExpression) {
    return node.object.type === AST_NODE_TYPES.Identifier && isGlobal(node.object) &&
      (node.object.name === "exports" || (node.object.name === "module" && memberPropertyName(node) === "exports"));
  }
  const first = node.arguments[0];
  return first?.type === AST_NODE_TYPES.Identifier && first.name === "exports" && isGlobal(first) &&
    node.callee.type === AST_NODE_TYPES.MemberExpression &&
    node.callee.object.type === AST_NODE_TYPES.Identifier && node.callee.object.name === "Object" &&
    isGlobal(node.callee.object) && CJS_OBJECT_EXPORT_METHODS.has(memberPropertyName(node.callee) ?? "");
}

function memberPropertyName(node: TSESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier) return node.property.name;
  return node.computed && node.property.type === AST_NODE_TYPES.Literal && typeof node.property.value === "string"
    ? node.property.value
    : null;
}
