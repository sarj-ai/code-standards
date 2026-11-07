/**
 * @fileoverview stable-value-binding — prove one value initializer site and no later assignments.
 */

import type { ESTree, Identifier, Node, SourceCode, TsReference, TsVariable } from "../types.js";
import { outerExpression, parentOf } from "./ast.js";
import { findVariable } from "./static-string.js";

export function typeOnlyReference(reference: TsReference): boolean {
  if (reference.isTypeReference && !reference.isValueReference) return true;
  let current = outerExpression(reference.identifier);
  let parent = parentOf(current);
  while (parent?.type === "TSQualifiedName" && parent.left === current) {
    current = parent;
    parent = parentOf(current);
  }
  return parent?.type === "TSTypeQuery" && parent.exprName === current;
}

export function stableValueBinding(
  variable: TsVariable,
  acceptRead?: (reference: TsReference) => boolean,
): boolean {
  let initializer: Node | undefined;
  return variable.references.every((reference) => {
    if (!reference.isWrite()) return acceptRead?.(reference) ?? true;
    if (reference.init !== true || (initializer !== undefined && initializer !== reference.identifier)) return false;
    initializer = reference.identifier;
    return true;
  });
}

export interface StableConstInitializer {
  readonly variable: TsVariable;
  readonly declaration: ESTree.VariableDeclarator;
  readonly value: ESTree.Expression;
}

/** Resolve an earlier local const initializer without treating property writes as binding writes. */
export function stableConstInitializer(
  source: Readonly<SourceCode>,
  identifier: Identifier,
): StableConstInitializer | null {
  const variable = findVariable(source.getScope(identifier), identifier.name);
  const declaration = variable?.defs[0]?.node;
  if (variable === null || variable.defs.length !== 1 ||
    declaration?.type !== "VariableDeclarator" ||
    declaration.id.type !== "Identifier" ||
    !isConstDeclaration(parentOf(declaration)) || declaration.init === null ||
    declaration.range[1] >= identifier.range[0] || !stableValueBinding(variable)) return null;
  return { variable, declaration, value: declaration.init };
}

export function isConstDeclaration(node: Node | null): boolean {
  return node?.type === "VariableDeclaration" && node.kind === "const";
}

/** Find the execution boundary owning a source expression. */
export function enclosingFunction(node: Node): ESTree.Function | ESTree.ArrowFunctionExpression | null {
  for (let current = parentOf(node); current !== null; current = parentOf(current)) {
    if (current.type === "ArrowFunctionExpression" ||
      current.type === "FunctionExpression" ||
      current.type === "FunctionDeclaration") return current;
  }
  return null;
}

/** Whether a member or one of its member descendants is an assignment target. */
export function writtenMember(node: ESTree.MemberExpression): boolean {
  let current: Node = outerExpression(node);
  for (let parent = parentOf(current); parent !== null; parent = parentOf(current)) {
    const target = enclosingTarget(current, parent);
    if (target === null) return writes(parent, current);
    current = target;
  }
  return false;
}

/** The member or pattern that writing `current` also writes, or null when `current` is the whole target. */
function enclosingTarget(current: Node, parent: Node): Node | null {
  if (parent.type === "MemberExpression" && parent.object === current ||
    parent.type === "ArrayPattern" || parent.type === "RestElement" ||
    parent.type === "AssignmentPattern" && parent.left === current) return outerExpression(parent);
  const pattern = parent.type === "Property" && parent.value === current ? parentOf(parent) : null;
  return pattern?.type === "ObjectPattern" ? pattern : null;
}

function writes(parent: Node, target: Node): boolean {
  return parent.type === "AssignmentExpression" && parent.left === target ||
    (parent.type === "ForOfStatement" || parent.type === "ForInStatement") && parent.left === target ||
    parent.type === "UpdateExpression" && parent.argument === target ||
    parent.type === "UnaryExpression" && parent.operator === "delete";
}
