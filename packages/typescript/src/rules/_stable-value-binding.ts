/**
 * @fileoverview _stable-value-binding — prove one value initializer site and no later assignments.
 */
import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { outerExpression } from "./_unwrap-expression.js";

type BindingReference = TSESLint.Scope.Variable["references"][number];

export function typeOnlyReference(reference: BindingReference): boolean {
  if (reference.isTypeReference && !reference.isValueReference) return true;
  let current = outerExpression(reference.identifier);
  while (current.parent?.type === AST_NODE_TYPES.TSQualifiedName && current.parent.left === current) {
    current = current.parent;
  }
  return current.parent?.type === AST_NODE_TYPES.TSTypeQuery && current.parent.exprName === current;
}

export function stableValueBinding(
  variable: TSESLint.Scope.Variable,
  acceptRead?: (reference: BindingReference) => boolean,
): boolean {
  let initializer: TSESTree.Node | undefined;
  return variable.references.every((reference) => {
    if (!reference.isWrite()) return acceptRead?.(reference) ?? true;
    if (reference.init !== true || (initializer !== undefined && initializer !== reference.identifier)) return false;
    initializer = reference.identifier;
    return true;
  });
}
