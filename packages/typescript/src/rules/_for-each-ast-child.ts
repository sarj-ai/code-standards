/** @fileoverview _for-each-ast-child — visit parser-declared AST children through one checked reflection boundary. */

import type { ESTree, SourceCode } from "@oxlint/plugins";


export function forEachAstChild(
  node: ESTree.Node,
  visitorKeys: Readonly<SourceCode["visitorKeys"]>,
  visit: (child: ESTree.Node) => boolean | void,
): boolean {
  for (const key of visitorKeys[node.type] ?? []) {
    if (forEachAstChildKey(node, key, visit)) return true;
  }
  return false;
}

export function forEachAstChildKey(
  node: ESTree.Node,
  key: string,
  visit: (child: ESTree.Node) => boolean | void,
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

function isNode(value: unknown): value is ESTree.Node {
  return typeof value === "object" && value !== null && "type" in value && typeof value.type === "string";
}
