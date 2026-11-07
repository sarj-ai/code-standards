/**
 * @fileoverview _prefer-zod-parse-output-type-contracts — the typed helpers of `prefer-zod-parse-output-type`, on tsrs.
 *
 * Ports of the 18.x `_equivalent-zod-output-contracts.ts` helper and
 * the 18.x `_has-authoritative-output-contract.ts` helper from the `typescript`
 * checker to tsrs (TypeScript 7). Same algorithms; every checker call is a
 * synchronous tsrs request. The rule calls these only for the few return
 * contracts that already passed every cheaper check, so they are not batched.
 *
 * Differences forced by the API:
 * - ts-api-utils `isPropertyReadonlyInType` reads internal mapped-type
 *   modifiers. tsrs does not expose them, so this port asks the checker's own
 *   `isReadonlySymbol` for the property, plus ts-api-utils' readonly index
 *   signature rule for a property missing from the type.
 * - `getTypeOfSymbolAtLocation(property, declaration)` at a declaration node is
 *   `getNonMissingTypeOfSymbol(property)` in the checker; tsrs exposes that
 *   directly, so declaration handles need not be resolved.
 * - Types and symbols are compared by id.
 *
 * Enum values (SyntaxKind, SymbolFlags...) follow TypeScript 7 numbering and
 * come from the file's tsrs modules.
 */

import type { TsrsFile, TsrsNode, TsrsTypeFlags } from "../utils/tsrs-services.js";

// The subset of tsrs objects these helpers use.

export interface TsrsHandle {
  readonly kind: number;
  readonly path: string;
  resolve(): TsNode | undefined;
}

export interface TsSymbol {
  readonly id: number;
  readonly name: string;
  readonly escapedName: string;
  readonly flags: number;
  readonly declarations: readonly TsrsHandle[] | undefined;
}

export interface TsType {
  readonly id: number;
  readonly flags: number;
  readonly objectFlags: number;
  getSymbol(): TsSymbol | undefined;
  getAliasSymbol(): TsSymbol | undefined;
  getCallSignatures(): readonly TsSignature[];
  isUnionType(): boolean;
  isIntersectionType(): boolean;
  isTypeReference(): boolean;
  isTupleType(): boolean;
  getTypes(): readonly TsType[];
  getTarget(): TsType & { readonly readonly: boolean; readonly elementFlags: readonly number[] };
}

export interface TsSignature {
  readonly declaration?: TsrsHandle | undefined;
}

interface TsIndexInfo {
  readonly isReadonly: boolean;
}

/** A tsrs AST node with the fields these helpers read. */
export interface TsNode extends TsrsNode {
  readonly parent: TsNode;
  readonly name?: TsNode | undefined;
  readonly type?: TsNode | undefined;
  readonly initializer?: TsNode | undefined;
  readonly members?: readonly TsNode[] | undefined;
  readonly typeParameters?: readonly TsNode[] | undefined;
  readonly heritageClauses?: readonly (TsNode & { readonly types: readonly TsNode[] })[] | undefined;
  readonly modifiers?: readonly TsNode[] | undefined;
  getSourceFile(): TsNode & { readonly fileName: string; readonly text: string; readonly isDeclarationFile: boolean };
}

export interface TsChecker {
  getTypeAtLocation(node: TsNode): TsType;
  getSymbolAtLocation(node: TsNode): TsSymbol | undefined;
  getTypeFromTypeNode(node: TsNode): TsType;
  getContextualType(node: TsNode): TsType | undefined;
  getAwaitedType(type: TsType): TsType | undefined;
  getNonNullableType(type: TsType): TsType;
  getReturnTypeOfSignature(signature: TsSignature): TsType;
  getTypeOfSymbolAtLocation(symbol: TsSymbol, location: TsNode): TsType;
  getNonMissingTypeOfSymbol(symbol: TsSymbol): TsType;
  getPropertyOfType(type: TsType, name: string): TsSymbol | undefined;
  getPropertiesOfType(type: TsType): readonly TsSymbol[];
  getIndexInfosOfType(type: TsType): readonly TsIndexInfo[];
  getIndexInfoOfType(type: TsType, kind: number): TsIndexInfo | undefined;
  getSignaturesOfType(type: TsType, kind: number): readonly TsSignature[];
  getTypeArguments(type: TsType): readonly TsType[];
  isArrayType(type: TsType): boolean;
  isTypeAssignableTo(source: TsType, target: TsType): boolean;
  isReadonlySymbol(symbol: TsSymbol): boolean;
}

interface Enums {
  readonly SyntaxKind: Readonly<Record<string, number>>;
  readonly SymbolFlags: Readonly<Record<string, number>>;
  readonly SignatureKind: Readonly<Record<string, number>>;
  readonly IndexKind: Readonly<Record<string, number>>;
}

/** Everything the helpers need from one file's tsrs program. */
export interface Contracts {
  readonly checker: TsChecker;
  readonly flags: TsrsTypeFlags;
  readonly kinds: Enums;
}

/** The helpers' view of one file's tsrs program. */
export function contractsOf(file: TsrsFile): Contracts {
  // The enums, read by member name.
  const kinds = { SyntaxKind: file.ast.SyntaxKind, SymbolFlags: file.sync.SymbolFlags, SignatureKind: file.sync.SignatureKind, IndexKind: file.sync.IndexKind } as unknown as Enums;
  return { checker: file.checker as unknown as TsChecker, flags: file.flags, kinds };
}

const MAX_CONTRACT_PAIRS = 128;
const MAX_UNION_MEMBERS = 16;

type TypePair = readonly [TsType, TsType];

interface Comparison {
  readonly env: Contracts;
  readonly unsafe: number;
  readonly pending: TypePair[];
  readonly seen: Map<number, Set<number>>;
  pairs: number;
}

/** Assignability alone ignores readonly properties and additional optional keys. */
export function equivalentZodOutputContracts(env: Contracts, parsed: TsType, contract: TsType): boolean {
  const unsafe = env.flags.Any | env.flags.Unknown | env.flags.Never;
  const comparison: Comparison = { env, unsafe, pending: [[parsed, contract]], seen: new Map(), pairs: 0 };
  while (comparison.pending.length > 0) {
    const pair = comparison.pending.pop();
    if (pair === undefined) break;
    const [left, right] = pair;
    if (((left.flags | right.flags) & unsafe) !== 0) return false;
    if (left.id === right.id || seenPair(comparison, left, right)) continue;
    if (comparison.pairs >= MAX_CONTRACT_PAIRS) return false;
    comparison.pairs += 1;
    if (!equivalentPair(comparison, left, right)) return false;
  }
  return true;
}

function seenPair(comparison: Comparison, left: TsType, right: TsType): boolean {
  const rights = comparison.seen.get(left.id) ?? new Set<number>();
  if (rights.has(right.id)) return true;
  rights.add(right.id);
  comparison.seen.set(left.id, rights);
  return false;
}

function equivalentPair(comparison: Comparison, left: TsType, right: TsType): boolean {
  const { checker } = comparison.env;
  if (!mutuallyAssignable(checker, left, right)) return false;
  if (left.isUnionType() || right.isUnionType()) return equivalentUnions(comparison, left, right);
  const leftContainer = checker.isArrayType(left) || left.isTupleType();
  const rightContainer = checker.isArrayType(right) || right.isTupleType();
  if (leftContainer || rightContainer) return equivalentContainers(comparison, left, right);
  if (hasClassDeclaration(comparison.env, left) || hasClassDeclaration(comparison.env, right)) return false;
  if (!objectLike(comparison.env, left) || !objectLike(comparison.env, right)) return false;
  return equivalentProperties(comparison, left, right);
}

function mutuallyAssignable(checker: TsChecker, left: TsType, right: TsType): boolean {
  return checker.isTypeAssignableTo(left, right) && checker.isTypeAssignableTo(right, left);
}

function equivalentUnions(comparison: Comparison, left: TsType, right: TsType): boolean {
  if (!left.isUnionType() || !right.isUnionType()) return false;
  const leftTypes = left.getTypes();
  const rightTypes = right.getTypes();
  if (leftTypes.length !== rightTypes.length || leftTypes.length > MAX_UNION_MEMBERS) return false;
  const matched = new Set<number>();
  for (const member of leftTypes) {
    const candidates = rightTypes.filter((other) => mutuallyAssignable(comparison.env.checker, member, other));
    const [only] = candidates;
    if (candidates.length !== 1 || only === undefined || matched.has(only.id)) return false;
    matched.add(only.id);
    if (!queuePair(comparison, member, only)) return false;
  }
  return true;
}

function queuePair(comparison: Comparison, left: TsType, right: TsType): boolean {
  if (((left.flags | right.flags) & comparison.unsafe) !== 0) return false;
  if (left.id === right.id) return true;
  if (comparison.pending.length >= MAX_CONTRACT_PAIRS) return false;
  comparison.pending.push([left, right]);
  return true;
}

function equivalentContainers(comparison: Comparison, left: TsType, right: TsType): boolean {
  const { checker, kinds } = comparison.env;
  if (!left.isTypeReference() || !right.isTypeReference()) return false;
  const leftTuple = left.isTupleType();
  const rightTuple = right.isTupleType();
  if (leftTuple !== rightTuple) return false;
  if (leftTuple && rightTuple) {
    const leftTarget = left.getTarget();
    const rightTarget = right.getTarget();
    if (
      leftTarget.readonly !== rightTarget.readonly ||
      leftTarget.elementFlags.length !== rightTarget.elementFlags.length ||
      leftTarget.elementFlags.some((flag, index) => flag !== rightTarget.elementFlags[index])
    ) return false;
  }
  const leftIndex = checker.getIndexInfoOfType(left, kinds.IndexKind["Number"]!);
  const rightIndex = checker.getIndexInfoOfType(right, kinds.IndexKind["Number"]!);
  if (leftIndex?.isReadonly !== rightIndex?.isReadonly) return false;
  const leftArguments = checker.getTypeArguments(left);
  const rightArguments = checker.getTypeArguments(right);
  return leftArguments.length === rightArguments.length && leftArguments.every((argument, index) => {
    const other = rightArguments[index];
    return other !== undefined && queuePair(comparison, argument, other);
  });
}

function hasClassDeclaration(env: Contracts, type: TsType): boolean {
  const classKind = env.kinds.SyntaxKind["ClassDeclaration"];
  return type.getSymbol()?.declarations?.some((declaration) => declaration.kind === classKind) === true ||
    (type.isIntersectionType() && type.getTypes().some((part) => hasClassDeclaration(env, part)));
}

function objectLike(env: Contracts, type: TsType): boolean {
  return (type.flags & env.flags.Object) !== 0 || type.isIntersectionType();
}

function equivalentProperties(comparison: Comparison, left: TsType, right: TsType): boolean {
  const { env } = comparison;
  if (opaqueObject(env, left) || opaqueObject(env, right)) return false;
  const leftProperties = env.checker.getPropertiesOfType(left);
  const rightProperties = env.checker.getPropertiesOfType(right);
  if (leftProperties.length === 0 || leftProperties.length > MAX_CONTRACT_PAIRS || leftProperties.length !== rightProperties.length) return false;
  for (const property of leftProperties) {
    const other = env.checker.getPropertyOfType(right, property.name);
    if (other === undefined || !equivalentProperty(comparison, left, right, property, other)) return false;
  }
  return true;
}

function opaqueObject(env: Contracts, type: TsType): boolean {
  return env.checker.getIndexInfosOfType(type).length > 0 ||
    env.checker.getSignaturesOfType(type, env.kinds.SignatureKind["Call"]!).length > 0 ||
    env.checker.getSignaturesOfType(type, env.kinds.SignatureKind["Construct"]!).length > 0;
}

function equivalentProperty(comparison: Comparison, left: TsType, right: TsType, property: TsSymbol, other: TsSymbol): boolean {
  const { env } = comparison;
  if (opaqueProperty(env, property) || opaqueProperty(env, other)) return false;
  const optional = env.kinds.SymbolFlags["Optional"]!;
  if ((property.flags & optional) !== (other.flags & optional)) return false;
  if (propertyReadonlyInType(env, left, property) !== propertyReadonlyInType(env, right, other)) return false;
  // The original reads the type at the property's value (or first) declaration; one must exist.
  if ((property.declarations?.length ?? 0) === 0 || (other.declarations?.length ?? 0) === 0) return false;
  return queuePair(comparison, env.checker.getNonMissingTypeOfSymbol(property), env.checker.getNonMissingTypeOfSymbol(other));
}

/**
 * ts-api-utils `isPropertyReadonlyInType` for a property of a non-union type, by the checker's own readonly test.
 * With a single type part, a property the type lacks is never readonly there (a readonly index
 * signature only counts beside another union part that has the property).
 */
function propertyReadonlyInType(env: Contracts, type: TsType, property: TsSymbol): boolean {
  const found = env.checker.getPropertyOfType(type, property.name);
  return found !== undefined && env.checker.isReadonlySymbol(found);
}

function opaqueProperty(env: Contracts, property: TsSymbol): boolean {
  return property.declarations?.some((declaration) =>
    is(env, declaration, "GetAccessor", "SetAccessor", "MethodDeclaration", "MethodSignature")) === true;
}

// has-authoritative-output-contract

interface Authority {
  readonly env: Contracts;
  readonly contract: TsSymbol;
}

function is(env: Contracts, node: { readonly kind: number } | undefined, ...names: string[]): boolean {
  return node !== undefined && names.some((name) => env.kinds.SyntaxKind[name] === node.kind);
}

function sameNode(left: TsNode | undefined, right: TsNode | undefined): boolean {
  return left !== undefined && right !== undefined && left.kind === right.kind && left.pos === right.pos &&
    left.end === right.end && left.getSourceFile().fileName === right.getSourceFile().fileName;
}

/** A local parser must not take ownership from an independently declared output contract. */
export function hasAuthoritativeOutputContract(env: Contracts, output: TsNode, contract: TsSymbol): boolean {
  const callable = enclosingCallable(env, output);
  if (callable === undefined) return false;
  const authority: Authority = { env, contract };
  const { checker } = env;
  if (is(env, callable, "MethodDeclaration", "GetAccessor")) return memberContract(authority, callable);
  const binding = callable.parent;
  if (is(env, binding, "VariableDeclaration", "PropertyDeclaration") && sameNode(binding.initializer, callable) && binding.type !== undefined &&
    callableContract(authority, checker.getTypeFromTypeNode(binding.type))) return true;
  if (is(env, binding, "PropertyDeclaration") && sameNode(binding.initializer, callable) && memberContract(authority, binding)) return true;
  const contextual = checker.getContextualType(callable);
  return contextual !== undefined && callableContract(authority, contextual, callable);
}

function enclosingCallable(env: Contracts, output: TsNode): TsNode | undefined {
  for (let current: TsNode | undefined = output; current !== undefined; current = current.parent) {
    if (is(env, current, "MethodDeclaration", "GetAccessor", "ArrowFunction", "FunctionExpression")) return current;
    if (is(env, current, "FunctionDeclaration", "Constructor", "SetAccessor", "SourceFile")) return undefined;
  }
  return undefined;
}

function memberContract(authority: Authority, member: TsNode): boolean {
  const { env } = authority;
  // ts.getCombinedModifierFlags on a class or object member is its own modifiers.
  if (member.modifiers?.some((modifier) => is(env, modifier, "PrivateKeyword", "StaticKeyword")) === true ||
    is(env, member.name, "PrivateIdentifier")) return false;
  const owner = member.parent;
  const name = member.name === undefined ? undefined : env.checker.getSymbolAtLocation(member.name)?.name;
  if (name === undefined) return false;
  if (is(env, owner, "ObjectLiteralExpression")) {
    const contextual = env.checker.getContextualType(owner);
    return contextual !== undefined && propertyContract(authority, contextual, name, member, member);
  }
  if (!is(env, owner, "ClassDeclaration", "ClassExpression")) return false;
  for (const clause of owner.heritageClauses ?? []) {
    for (const heritage of clause.types) {
      if (propertyContract(authority, env.checker.getTypeAtLocation(heritage), name, member)) return true;
    }
  }
  return false;
}

function propertyContract(authority: Authority, type: TsType, name: string, member: TsNode, contextual?: TsNode): boolean {
  const { env } = authority;
  const property = env.checker.getPropertyOfType(type, name);
  if (property === undefined) return false;
  const declared = env.checker.getTypeOfSymbolAtLocation(property, member);
  if (!is(env, member, "GetAccessor")) return callableContract(authority, declared, contextual);
  return property.declarations?.some((handle) => {
    if (!is(env, handle, "PropertySignature", "PropertyDeclaration", "GetAccessor")) return false;
    const declaration = handle.resolve();
    if (declaration?.type === undefined || sameNode(declaration, member)) return false;
    return returnsContract(authority, contextual === undefined ? declared : env.checker.getTypeAtLocation(declaration.type));
  }) === true;
}

function callableContract(authority: Authority, type: TsType, contextual?: TsNode): boolean {
  const { checker } = authority.env;
  return type.getCallSignatures().some((signature) => {
    const declaration = signature.declaration?.resolve();
    if (declaration?.type === undefined || sameNode(declaration, contextual)) return false;
    // Contextual inference can obtain a generic return from this very body. Only a separately authored return type proves ownership.
    return returnsContract(authority, contextual === undefined ? checker.getReturnTypeOfSignature(signature) : checker.getTypeAtLocation(declaration.type));
  });
}

function returnsContract(authority: Authority, returned: TsType): boolean {
  const awaited = authority.env.checker.getAwaitedType(returned) ?? returned;
  return (awaited.isUnionType() ? awaited.getTypes() : [awaited])
    .some((member) => (member.getAliasSymbol() ?? member.getSymbol())?.id === authority.contract.id);
}
