/** @fileoverview import-specifier-name — imported names preserve binding identity across quoted spelling. */
import type { ESTree } from "../types.js";

export function importSpecifierName(node: ESTree.ImportSpecifier): string {
  return node.imported.type === "Identifier" ? node.imported.name : node.imported.value;
}
