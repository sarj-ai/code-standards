/** @fileoverview _scope — walk native lexical scopes and AST ancestors. */

import type { ESTree, Scope, SourceCode, Variable } from "@oxlint/plugins";

/** Resolve an identifier to its binding by walking lexical scopes upward. */
export function resolveVariable(
	sourceCode: SourceCode,
	identifier: Extract<ESTree.Node, { type: "Identifier" }>,
): Variable | null {
	return findVariable(sourceCode.getScope(identifier), identifier.name);
}


/** Find the nearest lexical binding with the given name. */
export function findVariable(scope: Scope | null, name: string): Variable | null {
  while (scope !== null) {
    const variable = scope.set.get(name);
    if (variable !== undefined) return variable;
    scope = scope.upper;
  }
  return null;
}

/** Remove syntax-only expression wrappers. */
export function unwrapExpression(node: ESTree.Node): ESTree.Node {
  while (
    node.type === "TSAsExpression" || node.type === "TSSatisfiesExpression" ||
    node.type === "TSNonNullExpression" || node.type === "TSTypeAssertion" ||
    node.type === "TSInstantiationExpression" || node.type === "ChainExpression" ||
    node.type === "ParenthesizedExpression"
  ) node = node.expression;
  return node;
}

/** Match an unshadowed global identifier or its globalThis property. */
export function isGlobalReference(sourceCode: SourceCode, node: ESTree.Node, name: string): boolean {
  node = unwrapExpression(node);
  if (node.type === "Identifier" && node.name === name) {
    const variable = findVariable(sourceCode.getScope(node), name);
    return variable === null || variable.defs.length === 0;
  }
  if (node.type !== "MemberExpression" || node.computed || node.property.type !== "Identifier" || node.property.name !== name) return false;
  const object = unwrapExpression(node.object);
  return object.type === "Identifier" && object.name === "globalThis" &&
    isGlobalReference(sourceCode, object, "globalThis");
}

/** Ancestors in the native AST, root first. */
export function nodeAncestors(node: ESTree.Node): ESTree.Node[] {
  const result: ESTree.Node[] = [];
  for (let parent = node.parent; parent !== null; parent = parent.parent) result.push(parent);
  return result.toReversed();
}
