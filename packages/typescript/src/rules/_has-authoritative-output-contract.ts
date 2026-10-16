/**
 * @fileoverview _has-authoritative-output-contract — preserve return contracts owned by explicit ports.
 */
import ts from "typescript";

type Callable = ts.MethodDeclaration | ts.GetAccessorDeclaration | ts.ArrowFunction | ts.FunctionExpression;

interface Authority {
  readonly checker: ts.TypeChecker;
  readonly contract: ts.Symbol;
}

/** A local parser must not take ownership from an independently declared output contract. */
export function hasAuthoritativeOutputContract(checker: ts.TypeChecker, output: ts.Node, contract: ts.Symbol): boolean {
  const callable = enclosingCallable(output);
  if (callable === undefined) return false;
  const authority: Authority = { checker, contract };
  if (ts.isMethodDeclaration(callable) || ts.isGetAccessorDeclaration(callable)) return memberContract(authority, callable);
  const binding = callable.parent;
  if ((ts.isVariableDeclaration(binding) || ts.isPropertyDeclaration(binding)) && binding.initializer === callable && binding.type !== undefined &&
    callableContract(authority, checker.getTypeFromTypeNode(binding.type))) return true;
  if (ts.isPropertyDeclaration(binding) && binding.initializer === callable && memberContract(authority, binding)) return true;
  const contextual = checker.getContextualType(callable);
  return contextual !== undefined && callableContract(authority, contextual, callable);
}

function enclosingCallable(output: ts.Node): Callable | undefined {
  for (let current: ts.Node | undefined = output; current !== undefined; current = current.parent) {
    if (ts.isMethodDeclaration(current) || ts.isGetAccessorDeclaration(current) || ts.isArrowFunction(current) || ts.isFunctionExpression(current)) return current;
    if (ts.isFunctionDeclaration(current) || ts.isConstructorDeclaration(current) || ts.isSetAccessorDeclaration(current)) return undefined;
  }
  return undefined;
}

function memberContract(authority: Authority, member: ts.MethodDeclaration | ts.GetAccessorDeclaration | ts.PropertyDeclaration): boolean {
  if ((ts.getCombinedModifierFlags(member) & (ts.ModifierFlags.Private | ts.ModifierFlags.Static)) !== 0 || ts.isPrivateIdentifier(member.name)) return false;
  const owner = member.parent;
  const name = authority.checker.getSymbolAtLocation(member.name)?.getName();
  if (name === undefined) return false;
  if (ts.isObjectLiteralExpression(owner)) {
    const contextual = authority.checker.getContextualType(owner);
    return contextual !== undefined && propertyContract(authority, contextual, name, member, member);
  }
  if (!ts.isClassDeclaration(owner) && !ts.isClassExpression(owner)) return false;
  for (const clause of owner.heritageClauses ?? []) {
    for (const heritage of clause.types) {
      if (propertyContract(authority, authority.checker.getTypeAtLocation(heritage), name, member)) return true;
    }
  }
  return false;
}

function propertyContract(authority: Authority, type: ts.Type, name: string, member: ts.MethodDeclaration | ts.GetAccessorDeclaration | ts.PropertyDeclaration, contextual?: ts.Node): boolean {
  const property = authority.checker.getPropertyOfType(type, name);
  if (property === undefined) return false;
  const declared = authority.checker.getTypeOfSymbolAtLocation(property, member);
  if (!ts.isGetAccessorDeclaration(member)) return callableContract(authority, declared, contextual);
  return property.getDeclarations()?.some((declaration) => {
    if (!(ts.isPropertySignature(declaration) || ts.isPropertyDeclaration(declaration) || ts.isGetAccessorDeclaration(declaration)) || declaration.type === undefined || declaration === member) return false;
    return returnsContract(authority, contextual === undefined ? declared : authority.checker.getTypeAtLocation(declaration.type));
  }) === true;
}

function callableContract(authority: Authority, type: ts.Type, contextual?: ts.Node): boolean {
  return type.getCallSignatures().some((signature) => {
    const declaration = signature.declaration;
    if (declaration?.type === undefined || declaration === contextual) return false;
    // Contextual inference can obtain a generic return from this very body. Only a separately authored return type proves ownership.
    return returnsContract(authority, contextual === undefined ? authority.checker.getReturnTypeOfSignature(signature) : authority.checker.getTypeAtLocation(declaration.type));
  });
}

function returnsContract(authority: Authority, returned: ts.Type): boolean {
  const awaited = authority.checker.getAwaitedType(returned) ?? returned;
  return (awaited.isUnion() ? awaited.types : [awaited]).some((member) => (member.aliasSymbol ?? member.getSymbol()) === authority.contract);
}
