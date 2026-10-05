/** @fileoverview _for-each-own-ast-child — visit AST children through one checked reflection boundary. */

import type { ESTree } from "@oxlint/plugins";


import { forEachAstChildKey } from "./_for-each-ast-child.js";

export function forEachOwnAstChild(
  node: ESTree.Node,
  visit: (child: ESTree.Node) => boolean | void,
  includeKey: (key: string) => boolean = () => true,
): boolean {
  for (const key of Object.keys(node)) {
    if (key === "parent" || !includeKey(key)) continue;
    if (forEachAstChildKey(node, key, visit)) return true;
  }
  return false;
}
