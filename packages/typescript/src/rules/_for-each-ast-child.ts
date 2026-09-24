/** @fileoverview _for-each-ast-child — visit parser-declared AST children through one checked reflection boundary. */

import type { TSESLint, TSESTree } from "@typescript-eslint/utils";

export function forEachAstChild(
  node: TSESTree.Node,
  visitorKeys: Readonly<TSESLint.SourceCode.VisitorKeys>,
  visit: (child: TSESTree.Node) => boolean | void,
): boolean {
  for (const key of visitorKeys[node.type] ?? []) {
    if (forEachAstChildKey(node, key, visit)) return true;
  }
  return false;
}

export function forEachAstChildKey(
  node: TSESTree.Node,
  key: string,
  visit: (child: TSESTree.Node) => boolean | void,
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

function isNode(value: unknown): value is TSESTree.Node {
  return typeof value === "object" && value !== null && "type" in value && typeof value.type === "string";
}
