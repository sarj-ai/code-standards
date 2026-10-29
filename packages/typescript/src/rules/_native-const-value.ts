/** @fileoverview _native-const-value — reuse actual const initializers and erased value expressions. */
import ts from "typescript";

export function constInitializer(declaration: ts.Declaration | undefined): ts.Expression | undefined {
  if (!declaration || !ts.isVariableDeclaration(declaration) || !ts.isVariableDeclarationList(declaration.parent) ||
    (declaration.parent.flags & ts.NodeFlags.BlockScoped) !== ts.NodeFlags.Const) return undefined;
  let initializer = declaration.initializer;
  while (initializer && ts.isParenthesizedExpression(initializer)) initializer = initializer.expression;
  return initializer;
}

export function unassertedValue(node: ts.Node): ts.Node {
  let value = node;
  while (ts.isParenthesizedExpression(value) || ts.isAsExpression(value) || ts.isTypeAssertionExpression(value) || ts.isNonNullExpression(value) || ts.isSatisfiesExpression(value)) value = value.expression;
  return value;
}
