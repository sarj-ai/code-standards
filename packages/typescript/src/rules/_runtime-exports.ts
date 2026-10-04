/** @fileoverview _runtime-exports — classify runtime exports conservatively for module naming rules. */

import type { ESTree, SourceCode } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";

export const GENERIC_MODULE_STEMS: ReadonlySet<string> = new Set([
  "common", "helper", "helpers", "misc", "shared", "stuff", "util", "utils",
]);
const CJS_OBJECT_EXPORT_METHODS: ReadonlySet<string> = new Set(["assign", "defineProperties", "defineProperty"]);

type Emission = "runtime" | "erased" | "unknown";
interface RuntimeExport {
  readonly key: string;
  readonly name: string;
  readonly node: ESTree.Node;
}
interface RuntimeExports {
  readonly exports: readonly RuntimeExport[];
  readonly ambiguous: boolean;
}

/** Count public runtime keys, preserving unknowns instead of silently dropping them. */
export function runtimeExports(program: ESTree.Program): RuntimeExports {
  const bindings = localBindings(program);
  const exports = new Map<string, RuntimeExport>();
  let ambiguous = false;
  function add(key: string, name: string, node: ESTree.Node, emission: Emission): void {
    if (emission === "unknown") ambiguous = true;
    if (emission === "runtime") exports.set(key, { key, name, node });
  }
  function collectDefault(statement: ESTree.ExportDefaultDeclaration): void {
    const declaration = statement.declaration;
    if (declaration.type === "Identifier") {
      add("default", declaration.name, statement, bindings.get(declaration.name) ?? "unknown");
    } else if ("id" in declaration && declaration.id?.type === "Identifier") {
      add("default", declaration.id.name, declaration, declarationEmission(declaration));
    } else ambiguous = true;
  }
  function collectNamed(statement: ESTree.ExportNamedDeclaration): void {
    if (statement.exportKind === "type") return;
    if (statement.source !== null) {
      if (statement.specifiers.some((specifier) => specifier.exportKind !== "type")) ambiguous = true;
      return;
    }
    collectNamedDeclaration(statement);
    for (const specifier of statement.specifiers) {
      if (specifier.exportKind === "type") continue;
      const key = specifier.exported.type === "Identifier" ? specifier.exported.name : specifier.exported.value;
      const local = specifier.local.type === "Identifier" ? specifier.local.name : specifier.local.value;
      add(key, key === "default" ? local : key, specifier, bindings.get(local) ?? "unknown");
    }
  }
  function collectNamedDeclaration(statement: ESTree.ExportNamedDeclaration): void {
    const declaration = statement.declaration;
    if (declaration !== null) {
      if (declaration.type === "VariableDeclaration" &&
        declaration.declarations.some((item) => item.id.type !== "Identifier")) ambiguous = true;
      const names = declarationNames(declaration);
      if (names.length === 0 && declarationEmission(declaration) !== "erased") ambiguous = true;
      for (const name of names) add(name, name, declaration, bindings.get(name) ?? "unknown");
    }
  }
  for (const statement of program.body) {
    if (statement.type === "ExportAllDeclaration" && statement.exportKind !== "type") ambiguous = true;
    if (statement.type === "TSExportAssignment") ambiguous = true;
    if (statement.type === "ExportDefaultDeclaration") collectDefault(statement);
    if (statement.type === "ExportNamedDeclaration") collectNamed(statement);
  }
  return { exports: [...exports.values()], ambiguous };
}

function localBindings(program: ESTree.Program): ReadonlyMap<string, Emission> {
  const bindings = new Map<string, Emission>();
  function register(name: string, emission: Emission): void {
    const previous = bindings.get(name);
    if (previous === "runtime" || emission === "runtime") bindings.set(name, "runtime");
    else if (previous === "unknown" || emission === "unknown") bindings.set(name, "unknown");
    else bindings.set(name, "erased");
  }
  for (const statement of program.body) {
    if (statement.type === "ImportDeclaration") {
      for (const specifier of statement.specifiers) {
        const typeOnly = statement.importKind === "type" ||
          (specifier.type === "ImportSpecifier" && specifier.importKind === "type");
        register(specifier.local.name, typeOnly ? "erased" : "unknown");
      }
      continue;
    }
    const declaration = statement.type === "ExportNamedDeclaration" ||
      statement.type === "ExportDefaultDeclaration" ? statement.declaration : statement;
    if (declaration === null) continue;
    for (const name of declarationNames(declaration)) register(name, declarationEmission(declaration));
  }
  return bindings;
}

function declarationNames(declaration: ESTree.Node): string[] {
  if ("id" in declaration && declaration.id !== null) {
    let id: ESTree.Node = declaration.id;
    while (id.type === "TSQualifiedName") id = id.left;
    if (id.type === "Identifier") return [id.name];
  }
  if (declaration.type !== "VariableDeclaration") return [];
  return declaration.declarations.flatMap((item) => item.id.type === "Identifier" ? [item.id.name] : []);
}

function declarationEmission(declaration: ESTree.Node): Emission {
  if ("declare" in declaration && declaration.declare === true) return "erased";
  switch (declaration.type) {
    case "TSInterfaceDeclaration":
    case "TSTypeAliasDeclaration":
    case "TSDeclareFunction":
      return "erased";
    case "ClassDeclaration":
    case "FunctionDeclaration":
    case "VariableDeclaration":
      return "runtime";
    case "TSEnumDeclaration":
      return declaration.const ? "unknown" : "runtime";
    case "TSModuleDeclaration":
      return namespaceEmission(declaration);
    default:
      return "unknown";
  }
}

function namespaceEmission(declaration: ESTree.TSModuleDeclaration | ESTree.TSGlobalDeclaration): Emission {
  const { body } = declaration;
  if (body == null) return "unknown";
  if (body.body.length === 0) return "unknown";
  let ambiguous = false;
  for (const statement of body.body) {
    if (statement.type === "ExportNamedDeclaration" && statement.exportKind === "type") continue;
    const inner = statement.type === "ExportNamedDeclaration" ? statement.declaration : statement;
    const emission = inner === null ? "unknown" : declarationEmission(inner);
    if (emission === "runtime") return "runtime";
    if (emission === "unknown") ambiguous = true;
  }
  return ambiguous ? "unknown" : "erased";
}

/** Scope-aware CommonJS detection shared by both rules; mixed surfaces remain unknown. */
export function isCommonJsExportReference(
  node: ESTree.Node,
  sourceCode: Readonly<SourceCode>,
): boolean {
  function isGlobal(node: ESTree.BindingIdentifier): boolean {
    const variable = findVariable(sourceCode.getScope(node), node.name);
    return variable === null || variable.defs.length === 0;
  }
  if (node.type !== "CallExpression" && node.type !== "MemberExpression") return false;
  if (node.type === "MemberExpression") {
    return node.object.type === "Identifier" && isGlobal(node.object) &&
      (node.object.name === "exports" || (node.object.name === "module" && memberPropertyName(node) === "exports"));
  }
  const first = node.arguments[0];
  return first?.type === "Identifier" && first.name === "exports" && isGlobal(first) &&
    node.callee.type === "MemberExpression" &&
    node.callee.object.type === "Identifier" && node.callee.object.name === "Object" &&
    isGlobal(node.callee.object) && CJS_OBJECT_EXPORT_METHODS.has(memberPropertyName(node.callee) ?? "");
}

function memberPropertyName(node: ESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === "Identifier") return node.property.name;
  return node.computed && node.property.type === "Literal" && typeof node.property.value === "string"
    ? node.property.value
    : null;
}
