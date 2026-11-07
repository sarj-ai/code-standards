/**
 * @fileoverview existing-factory-contract-fix — reuse an authored factory contract.
 *
 * Port of the 18.x `_existing-factory-contract-fix.ts` helper. Oxlint sets absent
 * optional TS fields (`typeParameters`, `returnType`, `typeArguments`,
 * `accessibility`) to `null` where TS-ESTree leaves them `undefined`, and omits
 * TS-only fields (`implements`, `declare`, `abstract`) entirely in JS files.
 * Every "absent" check here accepts both `null` and `undefined`.
 */

import type { FixFn } from "@oxlint/plugins";

import type { ESTree, Identifier, Node, SourceCode } from "../types.js";
import { findVariable } from "./static-string.js";

/** A direct typed factory already chooses the closed contract this implementation satisfies. */
export function existingFactoryContractFix(
  sourceCode: Readonly<SourceCode>,
  candidate: ESTree.Class,
): FixFn | null {
  if (sourceCode.ast.body.length !== 4 || sourceCode.getAllComments().length !== 0) return null;
  const [contractStatement, worker, classStatement, factoryStatement] = sourceCode.ast.body;
  const contract = contractStatement?.type === "ExportNamedDeclaration" ? contractStatement.declaration : null;
  const implementation = classStatement?.type === "ExportNamedDeclaration" ? classStatement.declaration : classStatement;
  const factory = factoryStatement?.type === "ExportNamedDeclaration" ? factoryStatement.declaration : null;
  if (
    contract?.type !== "TSTypeAliasDeclaration" ||
    worker?.type !== "TSInterfaceDeclaration" ||
    implementation?.type !== "ClassDeclaration" ||
    implementation !== candidate ||
    !ordinaryClass(implementation) ||
    factory?.type !== "FunctionDeclaration" || !ordinaryFactory(factory)
  )
    return null;
  const operation = contractOperation(contract);
  if (operation === null || interfaceOperation(worker) !== operation) return null;
  if (
    implementation.id === null ||
    factory.id === null ||
    !uniqueDeclarations(sourceCode, [contract, worker, implementation, factory])
  )
    return null;
  const identifier = implementation.id;
  const field = retainedWorker(sourceCode, implementation, worker);
  if (
    field === null ||
    !forwardsOperation(implementation, field, operation) ||
    !factoryAuthority(sourceCode, factory, contract, worker, implementation)
  )
    return null;
  const name = sourceCode.getText(contract.id);
  return (fixer) => fixer.insertTextAfter(identifier, ` implements ${name}`);
}

function ordinaryClass(node: ESTree.Class): boolean {
  return (
    node.id !== null &&
    node.declare !== true &&
    node.abstract !== true &&
    node.decorators.length === 0 &&
    node.superClass === null &&
    (node.implements ?? []).length === 0 &&
    node.typeParameters == null &&
    node.body.body.length === 2
  );
}

function ordinaryFactory(node: ESTree.Function): boolean {
  return (
    node.id !== null &&
    node.declare !== true &&
    !node.async &&
    !node.generator &&
    node.typeParameters == null &&
    node.params.length === 1 &&
    node.body !== null &&
    node.body.body.length === 1
  );
}

function interfaceOperation(node: ESTree.TSInterfaceDeclaration): string | null {
  return !node.declare && node.extends.length === 0 && node.typeParameters == null
    ? singletonOperation(node.body.body)
    : null;
}

function contractOperation(node: ESTree.TSTypeAliasDeclaration): string | null {
  return !node.declare && node.typeParameters == null && node.typeAnnotation.type === "TSTypeLiteral"
    ? singletonOperation(node.typeAnnotation.members)
    : null;
}

function singletonOperation(members: readonly Node[]): string | null {
  const member = members[0];
  return members.length === 1 &&
    member?.type === "TSMethodSignature" &&
    member.kind === "method" &&
    !member.computed &&
    !member.optional &&
    member.key.type === "Identifier" &&
    member.params.length === 0 &&
    member.typeParameters == null &&
    member.returnType?.typeAnnotation.type === "TSVoidKeyword"
    ? member.key.name
    : null;
}

type NamedDeclaration = ESTree.TSInterfaceDeclaration | ESTree.TSTypeAliasDeclaration | ESTree.Class | ESTree.Function;

function uniqueDeclarations(sourceCode: Readonly<SourceCode>, declarations: readonly NamedDeclaration[]): boolean {
  const names = declarations.flatMap((declaration) => declaration.id === null ? [] : [declaration.id.name]);
  return (
    names.length === declarations.length &&
    new Set(names).size === names.length &&
    declarations.every(
      (declaration) => declaration.id !== null && sameBinding(sourceCode, declaration.id, declaration),
    )
  );
}

function sameBinding(sourceCode: Readonly<SourceCode>, reference: Identifier, declaration: Node): boolean {
  const binding = findVariable(sourceCode.getScope(reference), reference.name);
  return binding?.defs.length === 1 && binding.defs[0]?.node === declaration;
}

function retainedWorker(
  sourceCode: Readonly<SourceCode>,
  implementation: ESTree.Class,
  worker: ESTree.TSInterfaceDeclaration,
): string | null {
  const constructor = implementation.body.body[0];
  if (
    constructor?.type !== "MethodDefinition" ||
    constructor.value.type !== "FunctionExpression" ||
    constructor.kind !== "constructor" ||
    constructor.computed ||
    constructor.static ||
    constructor.decorators.length !== 0 ||
    constructor.optional === true ||
    (constructor.accessibility != null && constructor.accessibility !== "public") ||
    constructor.value.async ||
    constructor.value.generator ||
    constructor.value.typeParameters != null ||
    constructor.value.returnType != null ||
    constructor.value.body === null ||
    constructor.value.body.body.length !== 0 ||
    constructor.value.params.length !== 1
  )
    return null;
  const property = constructor.value.params[0];
  if (
    property?.type !== "TSParameterProperty" ||
    property.accessibility !== "private" ||
    !property.readonly ||
    property.override ||
    property.decorators.length !== 0 ||
    property.parameter.type !== "Identifier" ||
    property.parameter.optional ||
    !typeReference(sourceCode, property.parameter.typeAnnotation, worker)
  )
    return null;
  return property.parameter.name;
}

function typeReference(
  sourceCode: Readonly<SourceCode>,
  annotation: ESTree.TSTypeAnnotation | null | undefined,
  declaration: ESTree.TSInterfaceDeclaration | ESTree.TSTypeAliasDeclaration,
): boolean {
  const type = annotation?.typeAnnotation;
  return (
    type?.type === "TSTypeReference" &&
    type.typeArguments == null &&
    type.typeName.type === "Identifier" &&
    sameBinding(sourceCode, type.typeName, declaration)
  );
}

function forwardsOperation(implementation: ESTree.Class, field: string, operation: string): boolean {
  const method = implementation.body.body[1];
  if (
    method?.type !== "MethodDefinition" ||
    method.kind !== "method" ||
    method.value.type !== "FunctionExpression" ||
    method.computed ||
    method.static ||
    method.optional === true ||
    method.override === true ||
    method.decorators.length !== 0 ||
    (method.accessibility != null && method.accessibility !== "public") ||
    method.key.type !== "Identifier" ||
    method.key.name !== operation ||
    method.value.async ||
    method.value.generator ||
    method.value.typeParameters != null ||
    method.value.params.length !== 0 ||
    method.value.body === null ||
    method.value.body.body.length !== 1 ||
    method.value.returnType?.typeAnnotation.type !== "TSVoidKeyword"
  )
    return false;
  const statement = method.value.body.body[0];
  const call = statement?.type === "ExpressionStatement" ? statement.expression : null;
  return (
    call?.type === "CallExpression" &&
    !call.optional &&
    call.typeArguments == null &&
    call.arguments.length === 0 &&
    forwardedMember(call.callee, field, operation)
  );
}

function forwardedMember(node: Node, field: string, operation: string): boolean {
  if (
    node.type !== "MemberExpression" ||
    node.computed ||
    node.optional ||
    node.property.type !== "Identifier" ||
    node.property.name !== operation
  )
    return false;
  const receiver = node.object;
  return (
    receiver.type === "MemberExpression" &&
    !receiver.computed &&
    !receiver.optional &&
    receiver.object.type === "ThisExpression" &&
    receiver.property.type === "Identifier" &&
    receiver.property.name === field
  );
}

function factoryAuthority(
  sourceCode: Readonly<SourceCode>,
  factory: ESTree.Function,
  contract: ESTree.TSTypeAliasDeclaration,
  worker: ESTree.TSInterfaceDeclaration,
  implementation: ESTree.Class,
): boolean {
  const parameter = factory.params[0];
  if (
    parameter?.type !== "Identifier" ||
    parameter.optional ||
    !typeReference(sourceCode, parameter.typeAnnotation, worker) ||
    !typeReference(sourceCode, factory.returnType, contract)
  )
    return false;
  const statement = factory.body?.body[0];
  const constructed = statement?.type === "ReturnStatement" ? statement.argument : null;
  if (
    constructed?.type !== "NewExpression" ||
    constructed.typeArguments != null ||
    constructed.callee.type !== "Identifier" ||
    !sameBinding(sourceCode, constructed.callee, implementation) ||
    constructed.arguments.length !== 1
  )
    return false;
  const argument = constructed.arguments[0];
  return argument?.type === "Identifier" && argument.name === parameter.name && sameBinding(sourceCode, argument, factory);
}
