/**
 * @fileoverview _literal-lookup-hoist-fix — hoist a private readonly literal lookup.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

/** A sole module entry reads its private readonly literal lookup only through native includes. */
export function literalLookupHoistFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.VariableDeclarator,
): TSESLint.ReportFixFunction | null {
  if (
    sourceCode.ast.body.length !== 1 ||
    sourceCode.getAllComments().length > 0 ||
    node.id.type !== AST_NODE_TYPES.Identifier ||
    !readonlyStrings(node.id.typeAnnotation?.typeAnnotation) ||
    node.init?.type !== AST_NODE_TYPES.ArrayExpression ||
    !node.init.elements.every(
      (element) =>
        element?.type === AST_NODE_TYPES.Literal &&
        typeof element.value === "string",
    )
  )
    return null;
  const statement = sourceCode.ast.body[0];
  if (
    statement?.type !== AST_NODE_TYPES.ExportNamedDeclaration ||
    statement.declaration?.type !== AST_NODE_TYPES.FunctionDeclaration
  )
    return null;
  const owner = statement.declaration;
  if (
    owner.id === null ||
    owner.async ||
    owner.declare ||
    owner.generator ||
    owner.typeParameters !== undefined ||
    owner.params.length !== 1 ||
    owner.body.body.length !== 2 ||
    owner.id.name === node.id.name
  )
    return null;
  const argument = owner.params[0];
  const [declaration, returned] = owner.body.body;
  if (
    argument?.type !== AST_NODE_TYPES.Identifier ||
    argument.optional ||
    argument.name === node.id.name ||
    argument.typeAnnotation?.typeAnnotation.type !==
      AST_NODE_TYPES.TSStringKeyword ||
    declaration?.type !== AST_NODE_TYPES.VariableDeclaration ||
    declaration.declare ||
    declaration.kind !== "const" ||
    declaration.declarations.length !== 1 ||
    declaration.declarations[0] !== node ||
    returned?.type !== AST_NODE_TYPES.ReturnStatement
  )
    return null;
  if (
    owner.returnType !== undefined &&
    owner.returnType.typeAnnotation.type !== AST_NODE_TYPES.TSBooleanKeyword
  )
    return null;
  if (!includesArgument(returned.argument, node.id.name, argument.name))
    return null;
  const newline = sourceCode.text.includes("\r\n") ? "\r\n" : "\n";
  return (fixer) => [
    fixer.insertTextBefore(
      statement,
      `${sourceCode.getText(declaration)}${newline}`,
    ),
    fixer.removeRange([declaration.range[0], returned.range[0]]),
  ];
}

function readonlyStrings(node: TSESTree.TypeNode | undefined): boolean {
  return (
    node?.type === AST_NODE_TYPES.TSTypeOperator &&
    node.operator === "readonly" &&
    node.typeAnnotation?.type === AST_NODE_TYPES.TSArrayType &&
    node.typeAnnotation.elementType.type === AST_NODE_TYPES.TSStringKeyword
  );
}

function includesArgument(
  node: TSESTree.Expression | null,
  collection: string,
  argument: string,
): boolean {
  if (
    node?.type !== AST_NODE_TYPES.CallExpression ||
    node.optional ||
    node.arguments.length !== 1 ||
    node.callee.type !== AST_NODE_TYPES.MemberExpression ||
    node.callee.optional
  )
    return false;
  const member = node.callee;
  const value = node.arguments[0];
  return (
    member.object.type === AST_NODE_TYPES.Identifier &&
    member.object.name === collection &&
    ASTUtils.getPropertyName(member) === "includes" &&
    value?.type === AST_NODE_TYPES.Identifier &&
    value.name === argument
  );
}
