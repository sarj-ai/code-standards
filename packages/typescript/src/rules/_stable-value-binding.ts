/**
 * @fileoverview _stable-value-binding — prove one value initializer site and no later assignments.
 */
import { ASTUtils, AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import type { TypeScriptSourceCode } from "./_eslint-rule.js";

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

export interface StableConstInitializer {
  readonly variable: TSESLint.Scope.Variable;
  readonly declaration: TSESTree.VariableDeclarator;
  readonly value: TSESTree.Expression;
}

/** Resolve an earlier local const initializer without treating property writes as binding writes. */
export function stableConstInitializer(
  source: Readonly<TypeScriptSourceCode>,
  identifier: TSESTree.Identifier,
): StableConstInitializer | null {
  const variable = ASTUtils.findVariable(source.getScope(identifier), identifier.name);
  const definition = variable?.defs[0];
  if (variable === null || variable.defs.length !== 1 ||
    definition?.node.type !== AST_NODE_TYPES.VariableDeclarator ||
    definition.node.id.type !== AST_NODE_TYPES.Identifier ||
    definition.node.parent.kind !== "const" || definition.node.init === null ||
    definition.node.range[1] >= identifier.range[0] || !stableValueBinding(variable)) return null;
  return { variable, declaration: definition.node, value: definition.node.init };
}

/** Find the execution boundary owning a source expression. */
export function enclosingFunction(node: TSESTree.Node): TSESTree.Node | null {
  for (let current = node.parent; current != null; current = current.parent) {
    if (current.type === AST_NODE_TYPES.ArrowFunctionExpression ||
      current.type === AST_NODE_TYPES.FunctionExpression ||
      current.type === AST_NODE_TYPES.FunctionDeclaration) return current;
  }
  return null;
}

/** Whether a member or one of its member descendants is an assignment target. */
export function writtenMember(node: TSESTree.MemberExpression): boolean {
  let current: TSESTree.Node = outerExpression(node);
  while (true) {
    const parent: TSESTree.Node | undefined = current.parent;
    if (parent == null) return false;
    if (parent.type === AST_NODE_TYPES.MemberExpression && parent.object === current ||
      parent.type === AST_NODE_TYPES.ArrayPattern || parent.type === AST_NODE_TYPES.RestElement ||
      parent.type === AST_NODE_TYPES.AssignmentPattern && parent.left === current) {
      current = outerExpression(parent);
      continue;
    }
    if (parent.type === AST_NODE_TYPES.Property && parent.value === current &&
      parent.parent.type === AST_NODE_TYPES.ObjectPattern) {
      current = parent.parent;
      continue;
    }
    break;
  }
  const parent = current.parent;
  if (parent == null) return false;
  return parent.type === AST_NODE_TYPES.AssignmentExpression && parent.left === current ||
    (parent.type === AST_NODE_TYPES.ForOfStatement || parent.type === AST_NODE_TYPES.ForInStatement) && parent.left === current ||
    parent.type === AST_NODE_TYPES.UpdateExpression && parent.argument === current ||
    parent.type === AST_NODE_TYPES.UnaryExpression && parent.operator === "delete";
}
