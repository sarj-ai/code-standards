/**
 * @fileoverview _literal-string-loop-fix — join closed literal-only string loops.
 */

import {
  AST_NODE_TYPES,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

/** A complete literal-only loop has no intermediate observer or coercion to preserve. */
export function literalStringLoopFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  assignment: TSESTree.AssignmentExpression,
): TSESLint.ReportFixFunction | null {
  if (
    sourceCode.ast.body.length !== 1 ||
    sourceCode.getAllComments().length > 0
  )
    return null;
  const entry = sourceCode.ast.body[0];
  if (
    entry?.type !== AST_NODE_TYPES.ExportNamedDeclaration ||
    entry.declaration?.type !== AST_NODE_TYPES.FunctionDeclaration
  )
    return null;
  const owner = entry.declaration;
  if (
    owner.async ||
    owner.declare ||
    owner.generator ||
    owner.params.length > 0 ||
    owner.typeParameters !== undefined ||
    owner.body.body.length !== 3
  )
    return null;
  const [declaration, loop, returned] = owner.body.body;
  if (
    declaration?.type !== AST_NODE_TYPES.VariableDeclaration ||
    declaration.declare ||
    declaration.kind !== "let" ||
    declaration.declarations.length !== 1 ||
    loop?.type !== AST_NODE_TYPES.ForOfStatement ||
    loop.await ||
    returned?.type !== AST_NODE_TYPES.ReturnStatement
  )
    return null;
  const accumulator = declaration.declarations[0];
  if (
    accumulator?.id.type !== AST_NODE_TYPES.Identifier ||
    accumulator.init?.type !== AST_NODE_TYPES.Literal ||
    typeof accumulator.init.value !== "string" ||
    returned.argument?.type !== AST_NODE_TYPES.Identifier ||
    returned.argument.name !== accumulator.id.name
  )
    return null;
  if (
    accumulator.id.typeAnnotation !== undefined &&
    accumulator.id.typeAnnotation.typeAnnotation.type !==
      AST_NODE_TYPES.TSStringKeyword
  )
    return null;
  const elements = literalLoopElements(loop, assignment, accumulator.id.name);
  if (elements === null) return null;
  const initializer = accumulator.init;
  const keyword = sourceCode.getFirstToken(declaration);
  if (keyword === null) return null;
  const fragments = [initializer, ...elements].map((node) =>
    sourceCode.getText(node),
  );
  return (fixer) => [
    fixer.replaceText(initializer, `[${fragments.join(", ")}].join("")`),
    fixer.replaceTextRange(keyword.range, "const"),
    fixer.removeRange([loop.range[0], returned.range[0]]),
  ];
}

function literalLoopElements(
  loop: TSESTree.ForOfStatement,
  assignment: TSESTree.AssignmentExpression,
  accumulator: string,
): TSESTree.Literal[] | null {
  if (
    loop.left.type !== AST_NODE_TYPES.VariableDeclaration ||
    loop.left.declare ||
    loop.left.kind !== "const" ||
    loop.left.declarations.length !== 1 ||
    loop.right.type !== AST_NODE_TYPES.ArrayExpression ||
    loop.right.elements.length < 2
  )
    return null;
  const item = loop.left.declarations[0];
  let statement: TSESTree.Statement | undefined = loop.body;
  if (loop.body.type === AST_NODE_TYPES.BlockStatement) {
    statement = loop.body.body.length === 1 ? loop.body.body[0] : undefined;
  }
  if (
    item?.id.type !== AST_NODE_TYPES.Identifier ||
    item.init !== null ||
    item.id.name === accumulator ||
    statement?.type !== AST_NODE_TYPES.ExpressionStatement ||
    statement.expression !== assignment ||
    !accumulatesItem(assignment, accumulator, item.id.name)
  )
    return null;
  const elements: TSESTree.Literal[] = [];
  for (const element of loop.right.elements) {
    if (
      element?.type !== AST_NODE_TYPES.Literal ||
      typeof element.value !== "string"
    )
      return null;
    elements.push(element);
  }
  return elements;
}

function accumulatesItem(
  node: TSESTree.AssignmentExpression,
  accumulator: string,
  item: string,
): boolean {
  if (!named(node.left, accumulator)) return false;
  if (node.operator === "+=") return named(node.right, item);
  if (node.operator !== "=") return false;
  const expression = node.right;
  if (
    expression.type === AST_NODE_TYPES.BinaryExpression &&
    expression.operator === "+"
  ) {
    return named(expression.left, accumulator) && named(expression.right, item);
  }
  return (
    expression.type === AST_NODE_TYPES.TemplateLiteral &&
    expression.expressions.length === 2 &&
    expression.quasis.every((quasi) => quasi.value.cooked === "") &&
    named(expression.expressions[0], accumulator) &&
    named(expression.expressions[1], item)
  );
}

function named(node: TSESTree.Node | undefined, name: string): boolean {
  return node?.type === AST_NODE_TYPES.Identifier && node.name === name;
}
