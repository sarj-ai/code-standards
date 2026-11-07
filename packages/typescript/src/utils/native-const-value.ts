/**
 * @fileoverview native-const-value — reuse
 * actual const initializers and erased value expressions, over tsrs nodes.
 */

import type { Expression, Node } from "tsrs/ast";

import type { NativeAst } from "./checked-native-source.js";

export function constInitializer(ast: NativeAst, declaration: Node | undefined): Expression | undefined {
  if (!declaration || !ast.isVariableDeclaration(declaration) || !ast.isVariableDeclarationList(declaration.parent) ||
    (declaration.parent.flags & ast.NodeFlags.BlockScoped) !== ast.NodeFlags.Const) return undefined;
  let initializer = declaration.initializer;
  while (initializer && ast.isParenthesizedExpression(initializer)) initializer = initializer.expression;
  return initializer;
}

export function unassertedValue(ast: NativeAst, node: Node): Node {
  let value = node;
  while (ast.isParenthesizedExpression(value) || ast.isAsExpression(value) || ast.isTypeAssertion(value) || ast.isNonNullExpression(value) ||
    ast.isSatisfiesExpression(value)) value = value.expression;
  return value;
}
