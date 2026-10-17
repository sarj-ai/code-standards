/** @fileoverview _contradictory-array-predicate — native array membership does not validate a primitive element contract. */
import { AST_NODE_TYPES, ASTUtils, type ParserServicesWithTypeInformation, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";
import { isTypeReference } from "ts-api-utils";

import { unwrapExpression } from "./_unwrap-expression.js";

type Check = (expression: TSESTree.Expression, parameter: TSESTree.Identifier, input: ts.Type, target: ts.Type) => boolean;
interface ArrayPredicateProof {
  readonly matches: Check;
  readonly observeConstructor: (member: TSESTree.MemberExpression | TSESTree.Property) => void;
  readonly stable: () => boolean;
}
const HOST_GLOBALS = ["globalThis", "window", "self", "global"] as const;
const PRIMITIVE_ELEMENTS = ts.TypeFlags.String | ts.TypeFlags.Number | ts.TypeFlags.Boolean | ts.TypeFlags.BigInt | ts.TypeFlags.ESSymbol;
const OBJECT_REFLECTION: ReadonlySet<string> = new Set(["getPrototypeOf", "getOwnPropertyDescriptor", "getOwnPropertyDescriptors", "prototype", "constructor", "__proto__"]);

/** Cache only scope objects owned by this immutable parsed file. */
export function contradictoryArrayPredicate(sourceCode: TSESLint.SourceCode, services: ParserServicesWithTypeInformation): ArrayPredicateProof {
  const checker = services.program.getTypeChecker();
  const stable = new WeakMap<TSESLint.Scope.Variable, boolean>();
  let constructorCapability = false;
  function matches(expression: TSESTree.Expression, parameter: TSESTree.Identifier, input: ts.Type, target: ts.Type): boolean {
    if ((input.flags & ts.TypeFlags.Unknown) === 0 || !plainPrimitiveArray(target, checker)) return false;
    const call = unwrapExpression(expression);
    if (call.type !== AST_NODE_TYPES.CallExpression || call.optional || call.arguments.length !== 1) return false;
    const argument = call.arguments[0];
    const callee = unwrapExpression(call.callee);
    if (argument?.type !== AST_NODE_TYPES.Identifier || callee.type !== AST_NODE_TYPES.MemberExpression || callee.optional ||
      ASTUtils.getPropertyName(callee) !== "isArray" || callee.object.type !== AST_NODE_TYPES.Identifier || callee.object.name !== "Array") return false;
    const declared = ASTUtils.findVariable(sourceCode.getScope(parameter), parameter.name);
    if (declared === null || declared !== ASTUtils.findVariable(sourceCode.getScope(argument), argument.name)) return false;
    const binding = nativeBinding(callee.object, sourceCode);
    if (binding === undefined || !stableArray(binding, sourceCode, stable)) return false;
    const signature = checker.getResolvedSignature(services.esTreeNodeToTSNodeMap.get(call));
    const declaration = signature?.getDeclaration();
    return declaration !== undefined && services.program.isSourceFileDefaultLibrary(declaration.getSourceFile());
  }
  return {
    matches,
    observeConstructor(member): void {
      const name = ASTUtils.getPropertyName(member, sourceCode.getScope(member));
      if (name === "constructor" || name === null && member.computed) constructorCapability = true;
    },
    stable(): boolean {
      // A structural receiver type cannot prove which runtime constructor escapes.
      return !constructorCapability;
    },
  };
}

function plainPrimitiveArray(target: ts.Type, checker: ts.TypeChecker): boolean {
  if (!checker.isArrayType(target) || !isTypeReference(target)) return false;
  const [element] = checker.getTypeArguments(target);
  return element !== undefined && (element.flags & PRIMITIVE_ELEMENTS) !== 0 &&
    (element.flags & (ts.TypeFlags.Enum | ts.TypeFlags.EnumLiteral | ts.TypeFlags.Intersection)) === 0;
}

function nativeBinding(identifier: TSESTree.Identifier, sourceCode: TSESLint.SourceCode): TSESLint.Scope.Variable | undefined {
  const binding = ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name);
  return binding !== null && binding.defs.length === 0 ? binding : undefined;
}

function stableArray(binding: TSESLint.Scope.Variable, sourceCode: TSESLint.SourceCode, cache: WeakMap<TSESLint.Scope.Variable, boolean>): boolean {
  const previous = cache.get(binding);
  if (previous !== undefined) return previous;
  const scope = sourceCode.scopeManager?.globalScope;
  const untouched = binding.references.every(ordinaryArrayReference) && HOST_GLOBALS.every(name => {
    const host = scope?.set.get(name);
    const unresolved = scope?.through.filter(reference => reference.identifier.name === name) ?? [];
    return (host === undefined || host.defs.length > 0 || host.references.every(ordinaryHostReference)) && unresolved.every(ordinaryHostReference);
  }) && namespaceReferences("Reflect", sourceCode).every(typeOnlyReference) &&
    namespaceReferences("Object", sourceCode).every(reference => typeOnlyReference(reference) || ordinaryObjectUse(reference.identifier));
  cache.set(binding, untouched);
  return untouched;
}

/** Reflection or namespace aliases can reveal the same constructor without an Array read. */
function namespaceReferences(name: string, sourceCode: TSESLint.SourceCode): readonly TSESLint.Scope.Reference[] {
  const scope = sourceCode.scopeManager?.globalScope;
  const binding = scope?.set.get(name);
  const known = binding?.defs.length === 0 ? binding.references : [];
  const unresolved = scope?.through.filter(reference => reference.identifier.name === name) ?? [];
  return [...known, ...unresolved];
}

function typeOnlyReference(reference: TSESLint.Scope.Reference): boolean {
  return !reference.isWrite() && reference.isTypeReference && !reference.isValueReference;
}

function ordinaryObjectUse(node: TSESTree.Node): boolean {
  const member = node.parent;
  if (member?.type !== AST_NODE_TYPES.MemberExpression || member.object !== node) return false;
  const name = ASTUtils.getPropertyName(member);
  return name !== null && !OBJECT_REFLECTION.has(name);
}

/** Extracted methods, aliases, writes and namespace arguments lose native ownership. */
function ordinaryArrayReference(reference: TSESLint.Scope.Reference): boolean {
  if (reference.isWrite()) return false;
  if (reference.isTypeReference && !reference.isValueReference) return true;
  return ordinaryArrayUse(reference.identifier);
}

function ordinaryArrayUse(node: TSESTree.Node): boolean {
  const member = node.parent;
  if (member?.type === AST_NODE_TYPES.TSTypeQuery) return true;
  if (member?.type !== AST_NODE_TYPES.MemberExpression || member.object !== node || member.optional || ASTUtils.getPropertyName(member) !== "isArray") return false;
  return member.parent.type === AST_NODE_TYPES.CallExpression && member.parent.callee === member && !member.parent.optional;
}

/** A visible host alias can replace the same constructor through another spelling. */
function ordinaryHostReference(reference: TSESLint.Scope.Reference): boolean {
  if (reference.isWrite()) return false;
  if (reference.isTypeReference && !reference.isValueReference) return true;
  let node: TSESTree.Node = reference.identifier;
  while (node.parent?.type === AST_NODE_TYPES.MemberExpression && node.parent.object === node) {
    const member: TSESTree.MemberExpression = node.parent;
    const name = ASTUtils.getPropertyName(member);
    if (name === null) return false;
    if (name === "Array") return ordinaryArrayUse(member);
    if (name === "Reflect") return false;
    if (name === "Object") return ordinaryObjectUse(member);
    if (!HOST_GLOBALS.some(host => host === name)) return true;
    node = member;
  }
  return false;
}
