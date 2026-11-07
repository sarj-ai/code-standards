/**
 * @fileoverview closed-object-contract — prove a finite structural member surface, over tsrs.
 *
 * Declarations come from tsrs as handles; they are resolved (fetching their file) only where the
 * original reads the declaration nodes. Property origins compare handles by file path and index.
 */

import type { InterfaceDeclaration, Node, TypeLiteralNode } from "tsrs/ast";
import type { NodeHandle, Type, TypeReference } from "tsrs/sync";

import { declarationNode, type NativeTypes } from "./checked-native-source.js";

interface ContractProof {
  readonly native: NativeTypes;
  readonly active: Set<Type>;
  readonly completed: Map<Type, boolean>;
  readonly origins: Map<string, string> | undefined;
}

/** Prove that native member lookup has a complete, finite structural key space. */
export function closedObjectContract(native: NativeTypes, type: Type, singlePropertyOrigins = false): boolean {
  return visitContract(type, { native, active: new Set(), completed: new Map(), origins: singlePropertyOrigins ? new Map() : undefined });
}

function visitContract(type: Type, proof: ContractProof): boolean {
  const known = proof.completed.get(type);
  if (known !== undefined) return known;
  if (proof.active.has(type)) return false;
  proof.active.add(type);
  const result = type.isIntersectionType() ? type.getTypes().every((part) => visitContract(part, proof)) : completeObject(type, proof);
  proof.active.delete(type);
  proof.completed.set(type, result);
  return result;
}

function completeObject(type: Type, proof: ContractProof): boolean {
  const { native } = proof;
  if (!ordinaryObject(type, native)) return false;
  if (proof.origins && !singleOrigins(type, proof.origins)) return false;
  // A symbol may also carry value declarations, notably the global Object constructor.
  const kinds = native.ast.SyntaxKind;
  const handles = type.getSymbol()?.declarations.filter((handle) => handle.kind === kinds.InterfaceDeclaration || handle.kind === kinds.TypeLiteral);
  if (!handles?.length) return false;
  return handles.every((handle) => {
    const declaration = declarationNode(native, handle);
    return declaration !== undefined && completeDeclaration(declaration as InterfaceDeclaration | TypeLiteralNode, proof);
  });
}

/** A recovered merged or overridden property cannot supply an unambiguous contract. */
function singleOrigins(type: Type, origins: Map<string, string>): boolean {
  for (const property of type.getProperties()) {
    const declarations = property.declarations;
    const declaration = declarations[0];
    if (!declaration || declarations.length !== 1) return false;
    const key = handleKey(declaration);
    if (origins.has(property.name) && origins.get(property.name) !== key) return false;
    origins.set(property.name, key);
  }
  return true;
}

function handleKey(handle: NodeHandle): string {
  return `${handle.path}#${handle.index}`;
}

function ordinaryObject(type: Type, native: NativeTypes): boolean {
  const { checker, sync } = native;
  if ((type.flags & sync.TypeFlags.Object) === 0 || type.isUnionType() || checker.getIndexInfosOfType(type).length > 0) return false;
  const objectFlags = (type as Type & { readonly objectFlags: number }).objectFlags;
  if ((objectFlags & (sync.ObjectFlags.Class | sync.ObjectFlags.Mapped)) !== 0) return false;
  const unsafe = sync.TypeFlags.Any | sync.TypeFlags.Unknown | sync.TypeFlags.TypeParameter;
  if ((objectFlags & sync.ObjectFlags.Reference) !== 0 &&
    checker.getTypeArguments(type as TypeReference).some((argument) => (argument.flags & unsafe) !== 0)) return false;
  return checker.getSignaturesOfType(type, sync.SignatureKind.Call).length === 0 &&
    checker.getSignaturesOfType(type, sync.SignatureKind.Construct).length === 0;
}

function completeDeclaration(declaration: InterfaceDeclaration | TypeLiteralNode, proof: ContractProof): boolean {
  const { ast, checker } = proof.native;
  if (!declaration.members.every((member) => finiteMember(member, proof.native))) return false;
  if (!ast.isInterfaceDeclaration(declaration)) return true;
  if (declaration.typeParameters?.length) return false;
  return (declaration.heritageClauses ?? []).every((heritage) =>
    heritage.types.every((base) => visitContract(checker.getTypeAtLocation(base), proof)));
}

function finiteMember(member: Node, native: NativeTypes): boolean {
  const { ast, checker, sync } = native;
  if (ast.isIndexSignatureDeclaration(member)) return false;
  const name = (member as { readonly name?: Node }).name;
  if (!name || !ast.isComputedPropertyName(name)) return true;
  const f = sync.TypeFlags;
  return (checker.getTypeAtLocation(name.expression).flags & (f.StringLiteral | f.NumberLiteral | f.UniqueESSymbol)) !== 0;
}
