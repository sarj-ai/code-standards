/**
 * @fileoverview _collection-property-fix — preserve authored property-check behavior.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

/** Make an existing property check explicit without changing its Proxy has-trap or type narrowing. */
export function collectionPropertyFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.BinaryExpression,
): TSESLint.ReportFixFunction | null {
  if (
    node.left.type !== AST_NODE_TYPES.Literal ||
    typeof node.left.value !== "string" ||
    node.right.type !== AST_NODE_TYPES.Identifier ||
    sourceCode.ast.body.length !== 1 ||
    sourceCode.getAllComments().length > 0
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
    owner.async ||
    owner.declare ||
    owner.generator ||
    owner.typeParameters !== undefined ||
    owner.params.length !== 1 ||
    owner.body.body.length !== 1
  )
    return null;
  const parameter = owner.params[0];
  const returned = owner.body.body[0];
  if (
    parameter?.type !== AST_NODE_TYPES.Identifier ||
    parameter.optional ||
    parameter.name !== node.right.name ||
    returned?.type !== AST_NODE_TYPES.ReturnStatement ||
    returned.argument !== node
  )
    return null;
  if (owner.returnType?.typeAnnotation.type !== AST_NODE_TYPES.TSBooleanKeyword)
    return null;
  const reflect = ASTUtils.findVariable(sourceCode.getScope(node), "Reflect");
  if ((reflect?.defs.length ?? 0) !== 0) return null;
  const replacement = `Reflect.has(${sourceCode.getText(node.right)}, ${sourceCode.getText(node.left)})`;
  return (fixer) => fixer.replaceText(node, replacement);
}
