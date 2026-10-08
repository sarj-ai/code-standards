/** @fileoverview _import-specifier-name — imported names preserve binding identity across quoted spelling. */
import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

export function importSpecifierName(node: TSESTree.ImportSpecifier): string {
  return node.imported.type === AST_NODE_TYPES.Identifier ? node.imported.name : node.imported.value;
}
