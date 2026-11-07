/** @fileoverview unused-private-binding — prove a private declaration has no observable source references. */

import type { FixFn } from "@oxlint/plugins";

import type { ESTree, Node, SourceCode, TsVariable } from "../types.js";
import { tsVariable } from "../types.js";
import { forEachOwnAstChild, parentOf } from "./ast.js";
import { retainsNamedTypeUses } from "./type-binding.js";

type PrivateDeclaration = ESTree.VariableDeclarator | ESTree.Class | ESTree.TSInterfaceDeclaration |
  ESTree.TSTypeAliasDeclaration | ESTree.TSEnumDeclaration | ESTree.Function;

/** Dynamic eval and script globals prevent a file-local non-observation proof. */
export function isUnusedPrivateBinding(
  sourceCode: SourceCode,
  declaration: PrivateDeclaration,
  identifier: Node & { name: string },
  filename: string,
  allowedDeclarations: readonly Node[] = [declaration],
): boolean {
  if (/\.d\.[cm]?ts$/u.test(filename)) return false;
  const bindings = sourceCode.getDeclaredVariables(declaration).map(tsVariable)
    .filter((binding) => binding.name === identifier.name);
  if (bindings.length === 0 || bindings.some((binding) => binding.defs.length !== allowedDeclarations.length ||
    binding.defs.some((definition) => !allowedDeclarations.includes(definition.node)) || binding.eslintUsed ||
    binding.references.some((reference) => reference.isRead() || reference.init !== true))) return false;
  if (hasIdentifierNamed(sourceCode, "eval")) return false;
  const statement = declaration.type === "VariableDeclarator" ? parentOf(declaration) : declaration;
  const container = statement === null ? null : parentOf(statement);
  if (container === null) return false;
  if (container.type === "ExportNamedDeclaration" || container.type === "ExportDefaultDeclaration") return false;
  if (container.type !== "Program") return container.type === "BlockStatement";
  return sourceCode.ast.body.some((node) => node.type === "ImportDeclaration" ||
    node.type === "ExportNamedDeclaration" || node.type === "ExportDefaultDeclaration" ||
    node.type === "ExportAllDeclaration");
}

/** Imported factories/namespaces must not be assigned, aliased, or passed outward. */
export function hasOnlyDirectFactoryUses(variable: TsVariable): boolean {
  return variable.references.every((reference) => {
    if (reference.isTypeReference && !reference.isValueReference) return true;
    const identifier = reference.identifier;
    const parent = parentOf(identifier);
    if (parent?.type === "CallExpression" && parent.callee === identifier) return true;
    return parent?.type === "MemberExpression" && parent.object === identifier && !parent.computed &&
      parentOf(parent)?.type === "CallExpression" && (parentOf(parent) as ESTree.CallExpression).callee === parent;
  });
}

const IDENTIFIER_NAMES = new WeakMap<Node, ReadonlySet<string>>();

/** Whether an identifier in the file has this name; the names are collected once per immutable AST without recursive tree walking. */
export function hasIdentifierNamed(sourceCode: SourceCode, name: string): boolean {
  // An identifier's source text is its name unless it spells a character as a Unicode escape.
  if (!sourceCode.text.includes(name) && !sourceCode.text.includes("\\u")) return false;
  const node = sourceCode.ast;
  let names = IDENTIFIER_NAMES.get(node);
  if (names === undefined) {
    const collected = new Set<string>();
    const pending: Node[] = [node];
    const seen = new WeakSet<Node>();
    while (pending.length > 0) {
      const current = pending.pop();
      if (current === undefined || seen.has(current)) continue;
      seen.add(current);
      if (current.type === "Identifier" || current.type === "JSXIdentifier") collected.add(current.name);
      forEachOwnAstChild(current, (child) => { pending.push(child); }, (key) => key !== "tokens" && key !== "comments");
    }
    names = collected;
    IDENTIFIER_NAMES.set(node, names);
  }
  return names.has(name);
}

/** Remove an unobserved private function's unsound narrowing contract, retaining its runtime check. */
export function privatePredicateBooleanFix(
  sourceCode: SourceCode,
  node: ESTree.Function | ESTree.ArrowFunctionExpression,
  annotation: ESTree.TSTypePredicate,
  filename: string,
): FixFn | null {
  if (!annotation.typeAnnotation || !retainsNamedTypeUses(sourceCode, annotation.typeAnnotation) ||
    node.type !== "FunctionDeclaration" || node.id === null ||
    !isUnusedPrivateBinding(sourceCode, node, node.id, filename) || sourceCode.getCommentsInside(annotation).length > 0) return null;
  const text = `boolean${sourceCode.getText(annotation).replace(/[^\r\n\u2028\u2029]/gu, "")}`;
  const neighbor = Math.max(0, annotation.range[0] - 1);
  const before = sourceCode.text.slice(neighbor, annotation.range[1] + 1).match(/\r\n|[\r\n\u2028\u2029]/gu) ?? [];
  const after = (sourceCode.text.slice(neighbor, annotation.range[0]) + text + sourceCode.text.slice(annotation.range[1], annotation.range[1] + 1))
    .match(/\r\n|[\r\n\u2028\u2029]/gu) ?? [];
  if (before.length !== after.length || before.some((ending, index) => ending !== after[index])) return null;
  return (fixer) => fixer.replaceText(annotation, text);
}
