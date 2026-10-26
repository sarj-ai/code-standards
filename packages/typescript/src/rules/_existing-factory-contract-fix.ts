/**
 * @fileoverview _existing-factory-contract-fix — reuse an authored factory contract.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

/** A direct typed factory already chooses the closed contract this implementation satisfies. */
export function existingFactoryContractFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  candidate: TSESTree.ClassDeclaration | TSESTree.ClassExpression,
): TSESLint.ReportFixFunction | null {
  if (
    sourceCode.ast.body.length !== 4 ||
    sourceCode.getAllComments().length !== 0
  )
    return null;
  const [contractStatement, worker, classStatement, factoryStatement] =
    sourceCode.ast.body;
  const contract =
    contractStatement?.type === AST_NODE_TYPES.ExportNamedDeclaration
      ? contractStatement.declaration
      : null;
  const implementation =
    classStatement?.type === AST_NODE_TYPES.ExportNamedDeclaration
      ? classStatement.declaration
      : classStatement;
  const factory =
    factoryStatement?.type === AST_NODE_TYPES.ExportNamedDeclaration
      ? factoryStatement.declaration
      : null;
  if (
    contract?.type !== AST_NODE_TYPES.TSTypeAliasDeclaration ||
    worker?.type !== AST_NODE_TYPES.TSInterfaceDeclaration ||
    implementation?.type !== AST_NODE_TYPES.ClassDeclaration ||
    implementation !== candidate ||
    !ordinaryClass(implementation) ||
    !ordinaryFactory(factory)
  )
    return null;
  const operation = contractOperation(contract);
  if (operation === null || interfaceOperation(worker) !== operation)
    return null;
  if (
    implementation.id === null ||
    factory.id === null ||
    !uniqueDeclarations(sourceCode, [contract, worker, implementation, factory])
  )
    return null;
  const identifier = implementation.id;
  if (identifier === null) return null;
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

function ordinaryClass(node: TSESTree.ClassDeclaration): boolean {
  return (
    node.id !== null &&
    !node.declare &&
    !node.abstract &&
    node.decorators.length === 0 &&
    node.superClass === null &&
    node.implements.length === 0 &&
    node.typeParameters === undefined &&
    node.body.body.length === 2
  );
}

function ordinaryFactory(
  node: TSESTree.Node | null | undefined,
): node is TSESTree.FunctionDeclaration {
  return (
    node?.type === AST_NODE_TYPES.FunctionDeclaration &&
    node.id !== null &&
    !node.declare &&
    !node.async &&
    !node.generator &&
    node.typeParameters === undefined &&
    node.params.length === 1 &&
    node.body.body.length === 1
  );
}

function interfaceOperation(
  node: TSESTree.TSInterfaceDeclaration,
): string | null {
  return !node.declare &&
    node.extends.length === 0 &&
    node.typeParameters === undefined
    ? singletonOperation(node.body.body)
    : null;
}

function contractOperation(
  node: TSESTree.TSTypeAliasDeclaration,
): string | null {
  return !node.declare &&
    node.typeParameters === undefined &&
    node.typeAnnotation.type === AST_NODE_TYPES.TSTypeLiteral
    ? singletonOperation(node.typeAnnotation.members)
    : null;
}

function singletonOperation(members: readonly TSESTree.Node[]): string | null {
  const member = members[0];
  return members.length === 1 &&
    member?.type === AST_NODE_TYPES.TSMethodSignature &&
    member.kind === "method" &&
    !member.computed &&
    !member.optional &&
    member.key.type === AST_NODE_TYPES.Identifier &&
    member.params.length === 0 &&
    member.typeParameters === undefined &&
    member.returnType?.typeAnnotation.type === AST_NODE_TYPES.TSVoidKeyword
    ? member.key.name
    : null;
}

function uniqueDeclarations(
  sourceCode: Readonly<TSESLint.SourceCode>,
  declarations: readonly (
    | TSESTree.TSInterfaceDeclaration
    | TSESTree.TSTypeAliasDeclaration
    | TSESTree.ClassDeclaration
    | TSESTree.FunctionDeclaration
  )[],
): boolean {
  const names = declarations.flatMap((declaration) =>
    declaration.id === null ? [] : [declaration.id.name],
  );
  return (
    names.length === declarations.length &&
    new Set(names).size === names.length &&
    declarations.every(
      (declaration) =>
        declaration.id !== null &&
        sameBinding(sourceCode, declaration.id, declaration),
    )
  );
}

function sameBinding(
  sourceCode: Readonly<TSESLint.SourceCode>,
  reference: TSESTree.Identifier,
  declaration: TSESTree.Node,
): boolean {
  const binding = ASTUtils.findVariable(
    sourceCode.getScope(reference),
    reference.name,
  );
  return binding?.defs.length === 1 && binding.defs[0]?.node === declaration;
}

function retainedWorker(
  sourceCode: Readonly<TSESLint.SourceCode>,
  implementation: TSESTree.ClassDeclaration,
  worker: TSESTree.TSInterfaceDeclaration,
): string | null {
  const constructor = implementation.body.body[0];
  if (
    constructor?.type !== AST_NODE_TYPES.MethodDefinition ||
    constructor.value.type !== AST_NODE_TYPES.FunctionExpression ||
    constructor.kind !== "constructor" ||
    constructor.computed ||
    constructor.static ||
    constructor.decorators.length !== 0 ||
    constructor.optional ||
    (constructor.accessibility !== undefined &&
      constructor.accessibility !== "public") ||
    constructor.value.async ||
    constructor.value.generator ||
    constructor.value.typeParameters !== undefined ||
    constructor.value.returnType !== undefined ||
    constructor.value.body.body.length !== 0 ||
    constructor.value.params.length !== 1
  )
    return null;
  const property = constructor.value.params[0];
  if (
    property?.type !== AST_NODE_TYPES.TSParameterProperty ||
    property.accessibility !== "private" ||
    !property.readonly ||
    property.override ||
    property.decorators.length !== 0 ||
    property.parameter.type !== AST_NODE_TYPES.Identifier ||
    property.parameter.optional ||
    !typeReference(sourceCode, property.parameter.typeAnnotation, worker)
  )
    return null;
  return property.parameter.name;
}

function typeReference(
  sourceCode: Readonly<TSESLint.SourceCode>,
  annotation: TSESTree.TSTypeAnnotation | undefined,
  declaration:
    TSESTree.TSInterfaceDeclaration | TSESTree.TSTypeAliasDeclaration,
): boolean {
  const type = annotation?.typeAnnotation;
  return (
    type?.type === AST_NODE_TYPES.TSTypeReference &&
    type.typeArguments === undefined &&
    type.typeName.type === AST_NODE_TYPES.Identifier &&
    sameBinding(sourceCode, type.typeName, declaration)
  );
}

function forwardsOperation(
  implementation: TSESTree.ClassDeclaration,
  field: string,
  operation: string,
): boolean {
  const method = implementation.body.body[1];
  if (
    method?.type !== AST_NODE_TYPES.MethodDefinition ||
    method.kind !== "method" ||
    method.value.type !== AST_NODE_TYPES.FunctionExpression ||
    method.computed ||
    method.static ||
    method.optional ||
    method.override ||
    method.decorators.length !== 0 ||
    (method.accessibility !== undefined && method.accessibility !== "public") ||
    method.key.type !== AST_NODE_TYPES.Identifier ||
    method.key.name !== operation ||
    method.value.async ||
    method.value.generator ||
    method.value.typeParameters !== undefined ||
    method.value.params.length !== 0 ||
    method.value.body.body.length !== 1 ||
    method.value.returnType?.typeAnnotation.type !==
      AST_NODE_TYPES.TSVoidKeyword
  )
    return false;
  const statement = method.value.body.body[0];
  const call =
    statement?.type === AST_NODE_TYPES.ExpressionStatement
      ? statement.expression
      : null;
  return (
    call?.type === AST_NODE_TYPES.CallExpression &&
    !call.optional &&
    call.typeArguments === undefined &&
    call.arguments.length === 0 &&
    forwardedMember(call.callee, field, operation)
  );
}

function forwardedMember(
  node: TSESTree.Node,
  field: string,
  operation: string,
): boolean {
  if (
    node.type !== AST_NODE_TYPES.MemberExpression ||
    node.computed ||
    node.optional ||
    node.property.type !== AST_NODE_TYPES.Identifier ||
    node.property.name !== operation
  )
    return false;
  const receiver = node.object;
  return (
    receiver.type === AST_NODE_TYPES.MemberExpression &&
    !receiver.computed &&
    !receiver.optional &&
    receiver.object.type === AST_NODE_TYPES.ThisExpression &&
    receiver.property.type === AST_NODE_TYPES.Identifier &&
    receiver.property.name === field
  );
}

function factoryAuthority(
  sourceCode: Readonly<TSESLint.SourceCode>,
  factory: TSESTree.FunctionDeclaration,
  contract: TSESTree.TSTypeAliasDeclaration,
  worker: TSESTree.TSInterfaceDeclaration,
  implementation: TSESTree.ClassDeclaration,
): boolean {
  const parameter = factory.params[0];
  if (
    parameter?.type !== AST_NODE_TYPES.Identifier ||
    parameter.optional ||
    !typeReference(sourceCode, parameter.typeAnnotation, worker) ||
    !typeReference(sourceCode, factory.returnType, contract)
  )
    return false;
  const statement = factory.body.body[0];
  const constructed =
    statement?.type === AST_NODE_TYPES.ReturnStatement
      ? statement.argument
      : null;
  if (
    constructed?.type !== AST_NODE_TYPES.NewExpression ||
    constructed.typeArguments !== undefined ||
    constructed.callee.type !== AST_NODE_TYPES.Identifier ||
    !sameBinding(sourceCode, constructed.callee, implementation) ||
    constructed.arguments.length !== 1
  )
    return false;
  const argument = constructed.arguments[0];
  return (
    argument?.type === AST_NODE_TYPES.Identifier &&
    argument.name === parameter.name &&
    sameBinding(sourceCode, argument, factory)
  );
}
