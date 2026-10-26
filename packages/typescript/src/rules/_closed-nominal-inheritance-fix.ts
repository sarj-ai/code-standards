/**
 * @fileoverview _closed-nominal-inheritance-fix — repair closed local nominal constructions.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
} from "@typescript-eslint/utils";
import ts from "typescript";

/** Repair one closed local construction against its already authored nominal runtime authority. */
export function closedNominalInheritanceFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  call: ts.NewExpression,
  consumer: ts.ClassDeclaration,
  implementation: ts.ClassDeclaration,
  contract: ts.ClassDeclaration,
): TSESLint.ReportFixFunction | null {
  const source = call.getSourceFile();
  if (
    source.text !== sourceCode.text ||
    source.statements.length !== 5 ||
    sourceCode.getAllComments().length > 0 ||
    [consumer, implementation, contract].some(
      (node) => node.getSourceFile() !== source,
    )
  )
    return null;
  const markers = source.statements.filter(ts.isExportDeclaration);
  if (
    markers.length !== 1 ||
    markers[0] === undefined ||
    !emptyModuleMarker(markers[0])
  )
    return null;
  const statements = source.statements.filter(
    (node) => !ts.isExportDeclaration(node),
  );
  if (
    statements[0] !== contract ||
    statements[1] !== consumer ||
    statements[2] !== implementation ||
    statements[3] === undefined ||
    !ts.isExpressionStatement(statements[3]) ||
    statements[3].expression !== call
  )
    return null;
  if (
    !plainClass(contract, ts.SyntaxKind.AbstractKeyword) ||
    !plainClass(consumer, null) ||
    !plainClass(implementation, null) ||
    contract.name === undefined ||
    consumer.name === undefined ||
    implementation.name === undefined ||
    new Set([contract.name.text, consumer.name.text, implementation.name.text])
      .size !== 3
  )
    return null;
  const method = emptyContractMethod(contract);
  if (
    method === null ||
    !emptyImplementation(implementation, method) ||
    !exactConsumer(sourceCode, consumer, contract.name.text) ||
    !exactConstruction(call, consumer.name.text, implementation.name.text)
  )
    return null;
  const name = implementation.name;
  const base = contract.name.getText(source);
  return (fixer) =>
    fixer.insertTextAfterRange(
      [name.getStart(source), name.end],
      ` extends ${base}`,
    );
}

function emptyModuleMarker(node: ts.ExportDeclaration): boolean {
  return (
    !node.isTypeOnly &&
    node.moduleSpecifier === undefined &&
    node.attributes === undefined &&
    node.exportClause !== undefined &&
    ts.isNamedExports(node.exportClause) &&
    node.exportClause.elements.length === 0
  );
}

function plainClass(
  node: ts.ClassDeclaration,
  modifier: ts.SyntaxKind.AbstractKeyword | null,
): boolean {
  const modifiers = ts.getModifiers(node) ?? [];
  return (
    node.name !== undefined &&
    node.typeParameters === undefined &&
    node.heritageClauses === undefined &&
    (ts.getDecorators(node)?.length ?? 0) === 0 &&
    modifiers.length === (modifier === null ? 0 : 1) &&
    (modifier === null || modifiers[0]?.kind === modifier)
  );
}

function emptyContractMethod(node: ts.ClassDeclaration): string | null {
  const method = node.members[0];
  if (
    node.members.length !== 1 ||
    method === undefined ||
    !ts.isMethodDeclaration(method) ||
    !ts.isIdentifier(method.name) ||
    method.name.text === "constructor" ||
    method.parameters.length !== 0 ||
    method.typeParameters !== undefined ||
    method.questionToken !== undefined ||
    method.asteriskToken !== undefined ||
    method.body !== undefined ||
    method.type?.kind !== ts.SyntaxKind.VoidKeyword ||
    method.modifiers?.length !== 1 ||
    method.modifiers[0]?.kind !== ts.SyntaxKind.AbstractKeyword
  )
    return null;
  return method.name.text;
}

function emptyImplementation(node: ts.ClassDeclaration, key: string): boolean {
  const method = node.members[0];
  return (
    node.members.length === 1 &&
    method !== undefined &&
    ts.isMethodDeclaration(method) &&
    ts.isIdentifier(method.name) &&
    method.name.text === key &&
    method.parameters.length === 0 &&
    method.typeParameters === undefined &&
    method.questionToken === undefined &&
    method.asteriskToken === undefined &&
    method.modifiers === undefined &&
    (method.type === undefined ||
      method.type.kind === ts.SyntaxKind.VoidKeyword) &&
    method.body?.statements.length === 0
  );
}

function exactConsumer(
  sourceCode: Readonly<TSESLint.SourceCode>,
  consumer: ts.ClassDeclaration,
  base: string,
): boolean {
  const constructor = consumer.members[0];
  if (
    consumer.members.length !== 1 ||
    constructor === undefined ||
    !ts.isConstructorDeclaration(constructor) ||
    constructor.modifiers !== undefined ||
    constructor.parameters.length !== 1 ||
    constructor.body?.statements.length !== 1
  )
    return false;
  const parameter = constructor.parameters[0];
  if (
    parameter === undefined ||
    !ts.isIdentifier(parameter.name) ||
    parameter.name.text === base ||
    parameter.initializer !== undefined ||
    parameter.questionToken !== undefined ||
    parameter.dotDotDotToken !== undefined ||
    parameter.modifiers?.length !== 1 ||
    parameter.modifiers[0]?.kind !== ts.SyntaxKind.ReadonlyKeyword ||
    parameter.type === undefined ||
    !ts.isTypeReferenceNode(parameter.type) ||
    !ts.isIdentifier(parameter.type.typeName) ||
    parameter.type.typeName.text !== base ||
    parameter.type.typeArguments !== undefined
  )
    return false;
  const guard = constructor.body.statements[0];
  if (
    guard === undefined ||
    !ts.isIfStatement(guard) ||
    guard.elseStatement !== undefined
  )
    return false;
  const condition = unparenthesized(guard.expression);
  if (
    !ts.isPrefixUnaryExpression(condition) ||
    condition.operator !== ts.SyntaxKind.ExclamationToken
  )
    return false;
  const comparison = unparenthesized(condition.operand);
  return (
    ts.isBinaryExpression(comparison) &&
    comparison.operatorToken.kind === ts.SyntaxKind.InstanceOfKeyword &&
    ts.isIdentifier(comparison.left) &&
    comparison.left.text === parameter.name.text &&
    ts.isIdentifier(comparison.right) &&
    comparison.right.text === base &&
    exactRejection(sourceCode, guard.thenStatement)
  );
}

function unparenthesized(node: ts.Expression): ts.Expression {
  let expression = node;
  while (ts.isParenthesizedExpression(expression))
    expression = expression.expression;
  return expression;
}

function exactRejection(
  sourceCode: Readonly<TSESLint.SourceCode>,
  statement: ts.Statement,
): boolean {
  const rejected =
    ts.isBlock(statement) && statement.statements.length === 1
      ? statement.statements[0]
      : statement;
  if (
    rejected === undefined ||
    !ts.isThrowStatement(rejected) ||
    rejected.expression === undefined ||
    !ts.isNewExpression(rejected.expression) ||
    !ts.isIdentifier(rejected.expression.expression) ||
    rejected.expression.expression.text !== "TypeError" ||
    rejected.expression.typeArguments !== undefined ||
    rejected.expression.arguments?.length !== 1 ||
    rejected.expression.arguments[0] === undefined ||
    !ts.isStringLiteral(rejected.expression.arguments[0])
  )
    return false;
  const identifier = sourceCode.getNodeByRangeIndex(
    rejected.expression.expression.getStart(),
  );
  return (
    identifier?.type === AST_NODE_TYPES.Identifier &&
    identifier.name === "TypeError" &&
    (ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name)
      ?.defs.length ?? 0) === 0
  );
}

function exactConstruction(
  node: ts.NewExpression,
  consumer: string,
  implementation: string,
): boolean {
  if (
    !ts.isIdentifier(node.expression) ||
    node.expression.text !== consumer ||
    node.typeArguments !== undefined ||
    node.arguments?.length !== 1
  )
    return false;
  const argument = node.arguments[0];
  return (
    argument !== undefined &&
    ts.isNewExpression(argument) &&
    ts.isIdentifier(argument.expression) &&
    argument.expression.text === implementation &&
    argument.typeArguments === undefined &&
    argument.arguments?.length === 0
  );
}
