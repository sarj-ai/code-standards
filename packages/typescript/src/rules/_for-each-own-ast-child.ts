/** @fileoverview _for-each-own-ast-child — visit AST children through one checked reflection boundary. */

import type { TSESTree } from "@typescript-eslint/utils";

import { forEachAstChildKey } from "./_for-each-ast-child.js";

export function forEachOwnAstChild(
  node: TSESTree.Node,
  visit: (child: TSESTree.Node) => boolean | void,
  includeKey: (key: string) => boolean = () => true,
): boolean {
  for (const key of Object.keys(node)) {
    if (key === "parent" || !includeKey(key)) continue;
    if (forEachAstChildKey(node, key, visit)) return true;
  }
  return false;
}
