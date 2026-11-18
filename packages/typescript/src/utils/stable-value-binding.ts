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

const VALUE_STABILITY = new WeakMap<Node, WeakMap<TsVariable, boolean>>();

export function stableValueBinding(
  variable: TsVariable,
  acceptRead?: (reference: TsReference) => boolean,
): boolean {
  if (acceptRead !== undefined) return inspectValueBinding(variable, acceptRead);
  let stability = VALUE_STABILITY.get(variable.scope.block);
  if (stability === undefined) {
    stability = new WeakMap();
    VALUE_STABILITY.set(variable.scope.block, stability);
  }
  const known = stability.get(variable);
  if (known !== undefined) return known;
  const result = inspectValueBinding(variable);
  stability.set(variable, result);
  return result;
}

function inspectValueBinding(variable: TsVariable, acceptRead?: (reference: TsReference) => boolean): boolean {
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

const CONST_INITIALIZERS = new WeakMap<ESTree.Program, WeakMap<TsVariable, StableConstInitializer | null>>();
const FUNCTION_DECLARATIONS = new WeakMap<ESTree.Program, WeakMap<TsVariable, ESTree.Function | null>>();

export function stableFunctionDeclaration(source: Readonly<SourceCode>, identifier: Identifier): ESTree.Function | null {
  const variable = findVariable(source.getScope(identifier), identifier.name);
  if (variable === null) return null;
  let declarations = FUNCTION_DECLARATIONS.get(source.ast);
  if (declarations === undefined) {
    declarations = new WeakMap();
    FUNCTION_DECLARATIONS.set(source.ast, declarations);
  }
  if (declarations.has(variable)) return declarations.get(variable) ?? null;
  const definition = variable.defs[0]?.node;
  const result = variable.defs.length === 1 && definition?.type === "FunctionDeclaration" && stableValueBinding(variable) ? definition : null;
  declarations.set(variable, result);
  return result;
}

/** Resolve an earlier local const initializer without treating property writes as binding writes. */
export function stableConstInitializer(
  source: Readonly<SourceCode>,
  identifier: Identifier,
): StableConstInitializer | null {
  const variable = findVariable(source.getScope(identifier), identifier.name);
  if (variable === null) return null;
  let initializers = CONST_INITIALIZERS.get(source.ast);
  if (initializers === undefined) {
    initializers = new WeakMap();
    CONST_INITIALIZERS.set(source.ast, initializers);
  }
  if (initializers.has(variable)) {
    const cached = initializers.get(variable);
    return cached !== undefined && cached !== null && cached.declaration.range[1] < identifier.range[0] ? cached : null;
  }
  const declaration = variable?.defs[0]?.node;
  if (variable.defs.length !== 1 ||
    declaration?.type !== "VariableDeclarator" ||
    declaration.id.type !== "Identifier" ||
    !isConstDeclaration(parentOf(declaration)) || declaration.init === null ||
    !stableValueBinding(variable)) {
    initializers.set(variable, null);
    return null;
  }
  const result = { variable, declaration, value: declaration.init };
  initializers.set(variable, result);
  return declaration.range[1] < identifier.range[0] ? result : null;
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
