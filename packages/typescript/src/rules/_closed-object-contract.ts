/** @fileoverview _closed-object-contract — prove a finite structural member surface. */
import ts from "typescript";

interface ContractProof {
  readonly checker: ts.TypeChecker;
  readonly active: Set<ts.Type>;
  readonly completed: WeakMap<ts.Type, boolean>;
  readonly origins: Map<string, ts.Declaration> | undefined;
}

/** Prove that native member lookup has a complete, finite structural key space. */
export function closedObjectContract(type: ts.Type, checker: ts.TypeChecker, singlePropertyOrigins = false): boolean {
  return visitContract(type, { checker, active: new Set(), completed: new WeakMap(),
    origins: singlePropertyOrigins ? new Map() : undefined });
}

function visitContract(type: ts.Type, proof: ContractProof): boolean {
  const known = proof.completed.get(type);
  if (known !== undefined) return known;
  if (proof.active.has(type)) return false;
  proof.active.add(type);
  const result = type.isIntersection()
    ? type.types.every((part) => visitContract(part, proof))
    : completeObject(type, proof);
  proof.active.delete(type);
  proof.completed.set(type, result);
  return result;
}

function completeObject(type: ts.Type, proof: ContractProof): boolean {
  if (!ordinaryObject(type, proof.checker)) return false;
  if (proof.origins && !singleOrigins(type, proof.origins)) return false;
  // A symbol may also carry value declarations, notably the global Object constructor.
  const declarations = type.getSymbol()?.getDeclarations()?.filter((declaration) => ts.isInterfaceDeclaration(declaration) || ts.isTypeLiteralNode(declaration));
  if (!declarations?.length) return false;
  return declarations.every((declaration) => completeDeclaration(declaration, proof));
}

/** A recovered merged or overridden property cannot supply an unambiguous contract. */
function singleOrigins(type: ts.Type, origins: Map<string, ts.Declaration>): boolean {
  for (const property of type.getProperties()) {
    const declarations = property.getDeclarations();
    const declaration = declarations?.[0];
    if (!declaration || declarations?.length !== 1 ||
      (origins.has(property.name) && origins.get(property.name) !== declaration)) return false;
    origins.set(property.name, declaration);
  }
  return true;
}

function ordinaryObject(type: ts.Type, checker: ts.TypeChecker): boolean {
  if ((type.flags & ts.TypeFlags.Object) === 0 || type.isUnion() || checker.getIndexInfosOfType(type).length > 0) return false;
  const object = type as ts.ObjectType;
  if ((object.objectFlags & (ts.ObjectFlags.Class | ts.ObjectFlags.Mapped)) !== 0) return false;
  if ((object.objectFlags & ts.ObjectFlags.Reference) !== 0 && checker.getTypeArguments(type as ts.TypeReference).some((argument) => (argument.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.TypeParameter)) !== 0)) return false;
  return checker.getSignaturesOfType(type, ts.SignatureKind.Call).length === 0 && checker.getSignaturesOfType(type, ts.SignatureKind.Construct).length === 0;
}

function completeDeclaration(declaration: ts.InterfaceDeclaration | ts.TypeLiteralNode, proof: ContractProof): boolean {
  if (!declaration.members.every((member) => finiteMember(member, proof.checker))) return false;
  if (!ts.isInterfaceDeclaration(declaration)) return true;
  if (declaration.typeParameters?.length) return false;
  return (declaration.heritageClauses ?? []).every((heritage) => heritage.types.every((base) => visitContract(proof.checker.getTypeAtLocation(base), proof)));
}

function finiteMember(member: ts.TypeElement, checker: ts.TypeChecker): boolean {
  if (ts.isIndexSignatureDeclaration(member)) return false;
  if (!member.name || !ts.isComputedPropertyName(member.name)) return true;
  return (checker.getTypeAtLocation(member.name.expression).flags & (ts.TypeFlags.StringLiteral | ts.TypeFlags.NumberLiteral | ts.TypeFlags.UniqueESSymbol)) !== 0;
}
