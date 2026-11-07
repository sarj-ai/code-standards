/**
 * @fileoverview ast — visit AST children through the parser's visitor keys or
 * a node's own keys, and erase TypeScript-only expression wrappers.
 */

import type { ESTree, Node } from "../types.js";

export type VisitorKeys = Readonly<Record<string, readonly string[]>>;

export function forEachAstChild(
  node: Node,
  visitorKeys: VisitorKeys,
  visit: (child: Node) => boolean | void,
): boolean {
  for (const key of visitorKeys[node.type] ?? []) {
    if (forEachAstChildKey(node, key, visit)) return true;
  }
  return false;
}

function forEachAstChildKey(
  node: Node,
  key: string,
  visit: (child: Node) => boolean | void,
): boolean {
  const value: unknown = (node as unknown as Record<string, unknown>)[key];
  if (Array.isArray(value)) {
    const children: readonly unknown[] = value;
    for (const child of children) if (isNode(child) && visit(child) === true) return true;
  } else if (isNode(value)) {
    if (visit(value) === true) return true;
  }
  return false;
}

export function forEachOwnAstChild(
  node: Node,
  visit: (child: Node) => boolean | void,
  includeKey: (key: string) => boolean = () => true,
): boolean {
  for (const key of Object.keys(node)) {
    if (key === "parent" || !includeKey(key)) continue;
    if (forEachAstChildKey(node, key, visit)) return true;
  }
  return false;
}

// eslint-disable-next-line @sarj/no-explicit-type-predicate -- Only parser-declared child keys of an existing ESTree node cross this native reflection boundary; this is not a general payload validator.
function isNode(value: unknown): value is Node {
  return typeof value === "object" && value !== null && "type" in value && typeof value.type === "string";
}

export function isErasedExpression(node: Node) {
  return node.type === "TSAsExpression" || node.type === "TSSatisfiesExpression" ||
    node.type === "TSNonNullExpression" || node.type === "TSTypeAssertion";
}

/** Remove TypeScript expression wrappers that have no runtime effect. */
export function unwrapExpression(node: Node): Node {
  while (isErasedExpression(node)) node = node.expression;
  return node;
}

/** Return the outermost erased wrapper that still denotes this expression. */
export function outerExpression(node: Node): Node {
  let parent = parentOf(node);
  while (parent !== null && isErasedExpression(parent) && parent.expression === node) {
    node = parent;
    parent = parentOf(node);
  }
  return node;
}

/** Resolve only a direct call argument, including erased wrappers around it. */
export function directArgumentCall(node: Node): ESTree.CallExpression | null {
  const argument = outerExpression(node);
  const call = parentOf(argument);
  return call?.type === "CallExpression" && call.arguments.some((item) => item === argument) ? call : null;
}

/** Every node but Program has a parent; Program's is null. */
export function parentOf(node: Node): Node | null {
  return node.parent;
}
