/**
 * @fileoverview _literal-identity-reduce-fix — remove unobservable identity-reducer copies.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

/** Returning a fresh primitive array needs none of an unobservable identity reducer's copies. */
export function literalIdentityReduceFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.CallExpression,
): TSESLint.ReportFixFunction | null {
  if (
    sourceCode.ast.body.length !== 1 ||
    sourceCode.getAllComments().length > 0 ||
    node.optional ||
    node.arguments.length !== 2 ||
    node.callee.type !== AST_NODE_TYPES.MemberExpression ||
    node.callee.optional ||
    ASTUtils.getPropertyName(node.callee) !== "reduce"
  )
    return null;
  const values = node.callee.object;
  if (
    values.type !== AST_NODE_TYPES.ArrayExpression ||
    values.elements.length === 0 ||
    !values.elements.every(
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
    owner.async ||
    owner.declare ||
    owner.generator ||
    owner.typeParameters !== undefined ||
    owner.params.length !== 0 ||
    owner.body.body.length !== 1 ||
    !stringArray(owner.returnType?.typeAnnotation)
  )
    return null;
  const returned = owner.body.body[0];
  if (
    returned?.type !== AST_NODE_TYPES.ReturnStatement ||
    returned.argument !== node ||
    node.typeArguments?.params.length !== 1 ||
    !stringArray(node.typeArguments.params[0])
  )
    return null;
  const [callback, seed] = node.arguments;
  if (
    seed?.type !== AST_NODE_TYPES.ArrayExpression ||
    seed.elements.length !== 0 ||
    callback?.type !== AST_NODE_TYPES.ArrowFunctionExpression ||
    callback.async ||
    callback.typeParameters !== undefined ||
    callback.returnType !== undefined ||
    callback.params.length !== 2 ||
    callback.body.type !== AST_NODE_TYPES.ArrayExpression ||
    callback.body.elements.length !== 2
  )
    return null;
  if (!identitySpread(sourceCode, callback)) return null;
  return (fixer) => fixer.replaceText(node, sourceCode.getText(values));
}

function stringArray(node: TSESTree.TypeNode | undefined): boolean {
  return (
    node?.type === AST_NODE_TYPES.TSArrayType &&
    node.elementType.type === AST_NODE_TYPES.TSStringKeyword
  );
}

function identitySpread(
  sourceCode: Readonly<TSESLint.SourceCode>,
  callback: TSESTree.ArrowFunctionExpression,
): boolean {
  const [accumulator, item] = callback.params;
  if (
    accumulator?.type !== AST_NODE_TYPES.Identifier ||
    item?.type !== AST_NODE_TYPES.Identifier ||
    accumulator.name === item.name ||
    accumulator.optional ||
    item.optional ||
    accumulator.typeAnnotation !== undefined ||
    item.typeAnnotation !== undefined ||
    callback.body.type !== AST_NODE_TYPES.ArrayExpression
  )
    return false;
  const [spread, appended] = callback.body.elements;
  if (
    spread?.type !== AST_NODE_TYPES.SpreadElement ||
    spread.argument.type !== AST_NODE_TYPES.Identifier ||
    appended?.type !== AST_NODE_TYPES.Identifier ||
    spread.argument.name !== accumulator.name ||
    appended.name !== item.name
  )
    return false;
  const bindings = sourceCode.getDeclaredVariables(callback);
  const left = bindings.find((variable) =>
    variable.identifiers.includes(accumulator),
  );
  const right = bindings.find((variable) =>
    variable.identifiers.includes(item),
  );
  return (
    left !== undefined &&
    right !== undefined &&
    ASTUtils.findVariable(
      sourceCode.getScope(spread.argument),
      spread.argument.name,
    ) === left &&
    ASTUtils.findVariable(sourceCode.getScope(appended), appended.name) ===
      right
  );
}
