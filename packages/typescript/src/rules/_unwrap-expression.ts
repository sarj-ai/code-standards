/**
 * @fileoverview _unwrap-expression — remove TypeScript expression wrappers that have no runtime effect.
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

export function unwrapExpression(node: TSESTree.Expression): TSESTree.Expression;
export function unwrapExpression(node: TSESTree.Expression | TSESTree.Super): TSESTree.Expression | TSESTree.Super;
export function unwrapExpression(node: TSESTree.Expression | TSESTree.PrivateIdentifier): TSESTree.Expression | TSESTree.PrivateIdentifier;
export function unwrapExpression(node: TSESTree.CallExpressionArgument): TSESTree.CallExpressionArgument;
export function unwrapExpression(node: TSESTree.Node): TSESTree.Node;
export function unwrapExpression(node: TSESTree.Node): TSESTree.Node {
  while (isErasedExpression(node)) {
    node = node.expression;
  }
  return node;
}

/** Return the outermost erased wrapper that still denotes this expression. */
export function outerExpression(node: TSESTree.Expression): TSESTree.Expression;
export function outerExpression(node: TSESTree.Node): TSESTree.Node;
export function outerExpression(node: TSESTree.Node): TSESTree.Node {
  while (node.parent !== undefined && node.parent !== null && isErasedExpression(node.parent) && node.parent.expression === node) node = node.parent;
  return node;
}

/** Resolve only a direct call argument, including erased wrappers around it. */
export function directArgumentCall(node: TSESTree.Node): TSESTree.CallExpression | null {
  const argument = outerExpression(node);
  const call = argument.parent;
  return call?.type === AST_NODE_TYPES.CallExpression && call.arguments.some(item => item === argument)
    ? call : null;
}

function isErasedExpression(node: TSESTree.Node): node is TSESTree.TSAsExpression | TSESTree.TSSatisfiesExpression | TSESTree.TSNonNullExpression | TSESTree.TSTypeAssertion {
  return node.type === AST_NODE_TYPES.TSAsExpression || node.type === AST_NODE_TYPES.TSSatisfiesExpression ||
    node.type === AST_NODE_TYPES.TSNonNullExpression || node.type === AST_NODE_TYPES.TSTypeAssertion;
}
