/**
 * @fileoverview _unwrap-expression — remove TypeScript expression wrappers that have no runtime effect.
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

export function unwrapExpression(node: TSESTree.Expression): TSESTree.Expression;
export function unwrapExpression(node: TSESTree.Expression | TSESTree.Super): TSESTree.Expression | TSESTree.Super;
export function unwrapExpression(node: TSESTree.Expression | TSESTree.PrivateIdentifier): TSESTree.Expression | TSESTree.PrivateIdentifier;
export function unwrapExpression(node: TSESTree.Node): TSESTree.Node;
export function unwrapExpression(node: TSESTree.Node): TSESTree.Node {
  while (
    node.type === AST_NODE_TYPES.TSAsExpression ||
    node.type === AST_NODE_TYPES.TSSatisfiesExpression ||
    node.type === AST_NODE_TYPES.TSNonNullExpression ||
    node.type === AST_NODE_TYPES.TSTypeAssertion
  ) {
    node = node.expression;
  }
  return node;
}
