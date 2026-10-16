/**
 * @fileoverview _equivalent-zod-output-contracts — preserve nested contracts that structural assignability erases.
 */
import { isPropertyReadonlyInType, isTupleTypeReference, isTypeReference } from "ts-api-utils";
import ts from "typescript";

const MAX_CONTRACT_PAIRS = 128;
const MAX_UNION_MEMBERS = 16;
const UNSAFE_TYPES = ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.Never;

type TypePair = readonly [ts.Type, ts.Type];

interface Comparison {
  readonly checker: ts.TypeChecker;
  readonly pending: TypePair[];
  readonly seen: Map<ts.Type, Set<ts.Type>>;
  pairs: number;
}

/** Assignability alone ignores readonly properties and additional optional keys. */
export function equivalentZodOutputContracts(checker: ts.TypeChecker, parsed: ts.Type, contract: ts.Type): boolean {
  const comparison: Comparison = { checker, pending: [[parsed, contract]], seen: new Map(), pairs: 0 };
  while (comparison.pending.length > 0) {
    const pair = comparison.pending.pop();
    if (pair === undefined) break;
    const [left, right] = pair;
    if (((left.flags | right.flags) & UNSAFE_TYPES) !== 0) return false;
    if (left === right || seenPair(comparison, left, right)) continue;
    if (comparison.pairs >= MAX_CONTRACT_PAIRS) return false;
    comparison.pairs += 1;
    if (!equivalentPair(comparison, left, right)) return false;
  }
  return true;
}

function seenPair(comparison: Comparison, left: ts.Type, right: ts.Type): boolean {
  const rights = comparison.seen.get(left) ?? new Set<ts.Type>();
  if (rights.has(right)) return true;
  rights.add(right);
  comparison.seen.set(left, rights);
  return false;
}

function equivalentPair(comparison: Comparison, left: ts.Type, right: ts.Type): boolean {
  if (!mutuallyAssignable(comparison.checker, left, right)) return false;
  if (left.isUnion() || right.isUnion()) return equivalentUnions(comparison, left, right);
  const leftContainer = comparison.checker.isArrayType(left) || isTupleTypeReference(left);
  const rightContainer = comparison.checker.isArrayType(right) || isTupleTypeReference(right);
  if (leftContainer || rightContainer) return equivalentContainers(comparison, left, right);
  if (hasClassDeclaration(left) || hasClassDeclaration(right)) return false;
  if (!objectLike(left) || !objectLike(right)) return false;
  return equivalentProperties(comparison, left, right);
}

function mutuallyAssignable(checker: ts.TypeChecker, left: ts.Type, right: ts.Type): boolean {
  return checker.isTypeAssignableTo(left, right) && checker.isTypeAssignableTo(right, left);
}

function equivalentUnions(comparison: Comparison, left: ts.Type, right: ts.Type): boolean {
  if (!left.isUnion() || !right.isUnion() || left.types.length !== right.types.length || left.types.length > MAX_UNION_MEMBERS) return false;
  const matched = new Set<ts.Type>();
  for (const member of left.types) {
    const candidates = right.types.filter((other) => mutuallyAssignable(comparison.checker, member, other));
    const [only] = candidates;
    if (candidates.length !== 1 || only === undefined || matched.has(only)) return false;
    matched.add(only);
    if (!queuePair(comparison, member, only)) return false;
  }
  return true;
}

function queuePair(comparison: Comparison, left: ts.Type, right: ts.Type): boolean {
  if (((left.flags | right.flags) & UNSAFE_TYPES) !== 0) return false;
  if (left === right) return true;
  if (comparison.pending.length >= MAX_CONTRACT_PAIRS) return false;
  comparison.pending.push([left, right]);
  return true;
}

function equivalentContainers(comparison: Comparison, left: ts.Type, right: ts.Type): boolean {
  if (!isTypeReference(left) || !isTypeReference(right)) return false;
  const leftTuple = isTupleTypeReference(left);
  const rightTuple = isTupleTypeReference(right);
  if (leftTuple !== rightTuple) return false;
  if (leftTuple && rightTuple && (
    left.target.readonly !== right.target.readonly ||
    left.target.elementFlags.length !== right.target.elementFlags.length ||
    left.target.elementFlags.some((flag, index) => flag !== right.target.elementFlags[index])
  )) return false;
  const leftIndex = comparison.checker.getIndexInfoOfType(left, ts.IndexKind.Number);
  const rightIndex = comparison.checker.getIndexInfoOfType(right, ts.IndexKind.Number);
  if (leftIndex?.isReadonly !== rightIndex?.isReadonly) return false;
  const leftArguments = comparison.checker.getTypeArguments(left);
  const rightArguments = comparison.checker.getTypeArguments(right);
  return leftArguments.length === rightArguments.length && leftArguments.every((argument, index) => {
    const other = rightArguments[index];
    return other !== undefined && queuePair(comparison, argument, other);
  });
}

function hasClassDeclaration(type: ts.Type): boolean {
  return type.getSymbol()?.getDeclarations()?.some(ts.isClassDeclaration) === true ||
    (type.isIntersection() && type.types.some(hasClassDeclaration));
}

function objectLike(type: ts.Type): boolean {
  return (type.flags & ts.TypeFlags.Object) !== 0 || type.isIntersection();
}

function equivalentProperties(comparison: Comparison, left: ts.Type, right: ts.Type): boolean {
  const { checker } = comparison;
  if (opaqueObject(checker, left) || opaqueObject(checker, right)) return false;
  const leftProperties = checker.getPropertiesOfType(left);
  const rightProperties = checker.getPropertiesOfType(right);
  if (leftProperties.length === 0 || leftProperties.length > MAX_CONTRACT_PAIRS || leftProperties.length !== rightProperties.length) return false;
  for (const property of leftProperties) {
    const other = checker.getPropertyOfType(right, property.getName());
    if (other === undefined || !equivalentProperty(comparison, left, right, property, other)) return false;
  }
  return true;
}

function opaqueObject(checker: ts.TypeChecker, type: ts.Type): boolean {
  return checker.getIndexInfosOfType(type).length > 0 ||
    checker.getSignaturesOfType(type, ts.SignatureKind.Call).length > 0 ||
    checker.getSignaturesOfType(type, ts.SignatureKind.Construct).length > 0;
}

function equivalentProperty(comparison: Comparison, left: ts.Type, right: ts.Type, property: ts.Symbol, other: ts.Symbol): boolean {
  const { checker } = comparison;
  if (opaqueProperty(property) || opaqueProperty(other)) return false;
  if ((property.flags & ts.SymbolFlags.Optional) !== (other.flags & ts.SymbolFlags.Optional)) return false;
  if (isPropertyReadonlyInType(left, property.getEscapedName(), checker) !== isPropertyReadonlyInType(right, other.getEscapedName(), checker)) return false;
  const declaration = property.valueDeclaration ?? property.getDeclarations()?.[0];
  const otherDeclaration = other.valueDeclaration ?? other.getDeclarations()?.[0];
  return declaration !== undefined && otherDeclaration !== undefined && queuePair(
    comparison,
    checker.getTypeOfSymbolAtLocation(property, declaration),
    checker.getTypeOfSymbolAtLocation(other, otherDeclaration),
  );
}

function opaqueProperty(property: ts.Symbol): boolean {
  return property.getDeclarations()?.some((declaration) => ts.isGetAccessorDeclaration(declaration) ||
    ts.isSetAccessorDeclaration(declaration) || ts.isMethodDeclaration(declaration) || ts.isMethodSignature(declaration)) === true;
}
