/** @fileoverview _closed-object-contract — prove a finite structural member surface. */
import ts from "typescript";

/** Prove that native member lookup has a complete, finite structural key space. */
export function closedObjectContract(type: ts.Type, checker: ts.TypeChecker, seen = new Set<ts.Type>()): boolean {
  if (seen.has(type)) return false;
  seen.add(type);
  if (type.isIntersection()) return type.types.every((part) => closedObjectContract(part, checker, new Set(seen)));
  if (!ordinaryObject(type, checker)) return false;
  // A symbol may also carry value declarations, notably the global Object constructor.
  const declarations = type.getSymbol()?.getDeclarations()?.filter((declaration) => ts.isInterfaceDeclaration(declaration) || ts.isTypeLiteralNode(declaration));
  if (!declarations?.length) return false;
  return declarations.every((declaration) => completeDeclaration(declaration, checker, seen));
}

function ordinaryObject(type: ts.Type, checker: ts.TypeChecker): boolean {
  if ((type.flags & ts.TypeFlags.Object) === 0 || type.isUnion() || checker.getIndexInfosOfType(type).length > 0) return false;
  const object = type as ts.ObjectType;
  if ((object.objectFlags & (ts.ObjectFlags.Class | ts.ObjectFlags.Mapped)) !== 0) return false;
  if ((object.objectFlags & ts.ObjectFlags.Reference) !== 0 && checker.getTypeArguments(type as ts.TypeReference).some((argument) => (argument.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.TypeParameter)) !== 0)) return false;
  return checker.getSignaturesOfType(type, ts.SignatureKind.Call).length === 0 && checker.getSignaturesOfType(type, ts.SignatureKind.Construct).length === 0;
}

function completeDeclaration(declaration: ts.InterfaceDeclaration | ts.TypeLiteralNode, checker: ts.TypeChecker, seen: ReadonlySet<ts.Type>): boolean {
  if (!declaration.members.every((member) => finiteMember(member, checker))) return false;
  if (!ts.isInterfaceDeclaration(declaration)) return true;
  if (declaration.typeParameters?.length) return false;
  return (declaration.heritageClauses ?? []).every((heritage) => heritage.types.every((base) => closedObjectContract(checker.getTypeAtLocation(base), checker, new Set(seen))));
}

function finiteMember(member: ts.TypeElement, checker: ts.TypeChecker): boolean {
  if (ts.isIndexSignatureDeclaration(member)) return false;
  if (!member.name || !ts.isComputedPropertyName(member.name)) return true;
  return (checker.getTypeAtLocation(member.name.expression).flags & (ts.TypeFlags.StringLiteral | ts.TypeFlags.NumberLiteral | ts.TypeFlags.UniqueESSymbol)) !== 0;
}
