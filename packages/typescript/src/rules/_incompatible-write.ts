/**
 * @fileoverview _incompatible-write — the typed half of `no-invalid-typed-mutation`, on tsrs.
 *
 * Mirrors the original's `declaredTargetType`, `typedDataProperty`,
 * `propertyWriteType` and `definiteType` with tsrs requests. Candidates are
 * rare (a native mutation of a local annotated const that passed every
 * untyped check), so the checks ask tsrs directly instead of batching.
 *
 * Two TypeScript calls have no direct counterpart and are replaced by their
 * TypeScript definition:
 * - `getTypeOfSymbolAtLocation(symbol, declaration)` with a declaration node
 *   (not an identifier) is `getNonMissingTypeOfSymbol(symbol)`;
 * - `signature.typeParameters === undefined`: tsrs gives an empty list where
 *   TypeScript leaves it undefined.
 */

import type { TsrsFile, TsrsNode, TsrsNodeHandle, TsrsSymbol, TsrsType } from "../utils/tsrs-services.js";

/** The tsrs objects and calls these checks read, beyond `tsrs-services.ts`'s subset. */
interface RemoteNode extends TsrsNode {
  readonly type?: RemoteNode | undefined;
  readonly questionToken?: RemoteNode | undefined;
}
interface Handle extends TsrsNodeHandle {
  resolve(): RemoteNode | undefined;
}
interface Signature {
  readonly declaration?: Handle | undefined;
  readonly typeParameters?: readonly unknown[] | undefined;
  getParameters(): readonly Symbol[];
}
interface Symbol extends TsrsSymbol {
  readonly declarations: readonly Handle[];
  readonly valueDeclaration: Handle | undefined;
}
interface Type extends Omit<TsrsType, "getTypes"> {
  isTypeReference(): boolean;
  isObjectType(): boolean;
  getTypes(): readonly Type[];
  getProperties(): readonly Symbol[];
  getCallSignatures(): readonly Signature[];
  getConstructSignatures(): readonly Signature[];
  getAliasTypeArguments(): readonly Type[];
}
interface Checker {
  getSymbolAtLocation(node: TsrsNode): Symbol | undefined;
  getTypeFromTypeNode(node: TsrsNode): Type;
  getTypeAtLocation(node: TsrsNode): Type;
  getIndexInfosOfType(type: Type): readonly unknown[];
  getResolvedSignature(node: TsrsNode): Signature | undefined;
  getPropertyOfType(type: Type, name: string): Symbol | undefined;
  getTypeOfSymbolAtLocation(symbol: Symbol, location: TsrsNode): Type;
  getNonMissingTypeOfSymbol(symbol: Symbol): Type;
  getTypeArguments(type: Type): readonly Type[];
  getReturnTypeOfSignature(signature: Signature): Type;
  isTypeAssignableTo(source: Type, target: Type): boolean;
  typeToString(type: Type): string;
}

export interface TypedWrite {
  readonly key: string;
  readonly value: TsrsNode;
}

export interface IncompatibleWrite {
  readonly index: number;
  readonly actual: string;
  readonly expected: string;
}

/** The original's typed half of `inspect`: the first write whose value is not assignable to its field. */
export function incompatibleWrite(
  file: TsrsFile,
  exactOptionalPropertyTypes: boolean,
  call: TsrsNode,
  targetNode: TsrsNode,
  writes: readonly (TypedWrite | null)[],
): IncompatibleWrite | null {
  const checker = file.checker as unknown as Checker;
  const { flags } = file;
  const { SyntaxKind } = file.ast;
  const { SymbolFlags, ObjectFlags } = file.sync;

  function definiteType(type: Type, seen = new Set<number>()): boolean {
    if (seen.has(type.id)) return true;
    if (seen.size >= 32) return false;
    seen.add(type.id);
    const unsafe = flags.Any | flags.Unknown | flags.Never | flags.TypeParameter | flags.Conditional | flags.IndexedAccess |
      flags.Substitution;
    if ((type.flags & unsafe) !== 0) return false;
    if ((type.flags & (flags.Union | flags.Intersection)) !== 0) return type.getTypes().every((part) => definiteType(part, seen));
    const reference = type.isTypeReference();
    const typeArguments = reference ? checker.getTypeArguments(type) : type.getAliasTypeArguments();
    if (!typeArguments.every((argument) => definiteType(argument, seen))) return false;
    if (!definiteSignatures(type, seen)) return false;
    if (reference || (type.flags & flags.Object) === 0) return true;
    return type.getProperties().every((property) =>
      declarationOf(property) !== undefined && definiteType(checker.getNonMissingTypeOfSymbol(property), seen));
  }

  function definiteSignatures(type: Type, seen: Set<number>): boolean {
    const signatures = type.getCallSignatures();
    if (signatures.length > 1) return false;
    return signatures.every((signature) => (signature.typeParameters?.length ?? 0) === 0 &&
      definiteType(checker.getReturnTypeOfSignature(signature), seen) &&
      signature.getParameters().every((parameter) =>
        declarationOf(parameter) !== undefined && definiteType(checker.getNonMissingTypeOfSymbol(parameter), seen)));
  }

  function declarationOf(symbol: Symbol): Handle | undefined {
    return symbol.valueDeclaration ?? symbol.declarations[0];
  }

  function declaredTargetType(): Type | undefined {
    const declaration = checker.getSymbolAtLocation(targetNode)?.valueDeclaration?.resolve();
    if (declaration === undefined || (declaration.kind !== SyntaxKind.VariableDeclaration && declaration.kind !== SyntaxKind.Parameter) ||
      declaration.type === undefined) return undefined;
    const type = checker.getTypeFromTypeNode(declaration.type);
    if (!definiteType(type) || (type.flags & (flags.Union | flags.Intersection)) !== 0 || (type.flags & flags.Object) === 0 ||
      checker.getIndexInfosOfType(type).length > 0 || type.getCallSignatures().length > 0 || type.getConstructSignatures().length > 0) return undefined;
    return type;
  }

  function propertyDeclaration(property: Symbol): RemoteNode | undefined {
    const declaration = property.declarations[0]?.resolve();
    return declaration !== undefined &&
      (declaration.kind === SyntaxKind.PropertySignature || declaration.kind === SyntaxKind.PropertyDeclaration)
      ? declaration : undefined;
  }

  function typedDataProperty(property: Symbol): boolean {
    return property.declarations.length === 1 && propertyDeclaration(property)?.type !== undefined;
  }

  /** Exact optional properties distinguish an omitted field from an explicitly undefined write. */
  function propertyWriteType(target: Type, property: Symbol): Type {
    const exposed = checker.getTypeOfSymbolAtLocation(property, targetNode);
    if (!exactOptionalPropertyTypes || (property.flags & SymbolFlags.Optional) === 0 ||
      (property.flags & SymbolFlags.Transient) !== 0) return exposed;
    if (target.getAliasTypeArguments().length > 0 ||
      (target.isTypeReference() && checker.getTypeArguments(target).length > 0) ||
      (target.isObjectType() && (target.objectFlags & (ObjectFlags.Mapped | ObjectFlags.Instantiated)) !== 0)) return exposed;
    const declaration = propertyDeclaration(property);
    if (declaration === undefined || declaration.questionToken === undefined || declaration.type === undefined) return exposed;
    const authored = checker.getTypeFromTypeNode(declaration.type);
    return definiteType(authored) && checker.isTypeAssignableTo(authored, exposed) ? authored : exposed;
  }

  const target = declaredTargetType();
  if (target === undefined) return null;
  const signature = checker.getResolvedSignature(call);
  if (signature?.declaration === undefined ||
    !file.isDefaultLibrarySymbol({ name: "", flags: 0, declarations: [signature.declaration] })) return null;
  for (const [index, write] of writes.entries()) {
    if (write === null) continue;
    const property = checker.getPropertyOfType(target, write.key);
    if (property === undefined || !typedDataProperty(property)) continue;
    const expected = propertyWriteType(target, property);
    const actual = checker.getTypeAtLocation(write.value);
    if (!definiteType(expected) || !definiteType(actual) || checker.isTypeAssignableTo(actual, expected)) continue;
    return { index, actual: checker.typeToString(actual), expected: checker.typeToString(expected) };
  }
  return null;
}
