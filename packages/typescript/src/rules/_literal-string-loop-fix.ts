/** @fileoverview _literal-string-loop-fix — join closed literal-only string loops. */

import type { FixFn } from "@oxlint/plugins";

import type { ESTree, Node, SourceCode } from "../types.js";
import { isPresent } from "../utils/is-present.js";
import { soleExportedFunction } from "./_closed-module.js";

/** A complete literal-only loop has no intermediate observer or coercion to preserve. */
export function literalStringLoopFix(sourceCode: SourceCode, assignment: ESTree.AssignmentExpression): FixFn | null {
  const entry = soleExportedFunction(sourceCode);
  if (entry === null || entry.owner.params.length > 0 || entry.body.length !== 3) return null;
  const [declaration, loop, returned] = entry.body;
  if (
    declaration?.type !== "VariableDeclaration" ||
    declaration.declare ||
    declaration.kind !== "let" ||
    declaration.declarations.length !== 1 ||
    loop?.type !== "ForOfStatement" ||
    loop.await ||
    returned?.type !== "ReturnStatement"
  )
    return null;
  const accumulator = declaration.declarations[0];
  if (
    accumulator?.id.type !== "Identifier" ||
    accumulator.init?.type !== "Literal" ||
    typeof accumulator.init.value !== "string" ||
    returned.argument?.type !== "Identifier" ||
    returned.argument.name !== accumulator.id.name ||
    (isPresent(accumulator.id.typeAnnotation) && accumulator.id.typeAnnotation.typeAnnotation.type !== "TSStringKeyword")
  )
    return null;
  const elements = literalLoopElements(loop, assignment, accumulator.id.name);
  if (elements === null) return null;
  const initializer = accumulator.init;
  const keyword = sourceCode.getFirstToken(declaration);
  if (keyword === null) return null;
  const fragments = [initializer, ...elements].map((node) => sourceCode.getText(node));
  return (fixer) => [
    fixer.replaceText(initializer, `[${fragments.join(", ")}].join("")`),
    fixer.replaceTextRange([keyword.range[0], keyword.range[1]], "const"),
    fixer.removeRange([loop.range[0], returned.range[0]]),
  ];
}

function literalLoopElements(
  loop: ESTree.ForOfStatement,
  assignment: ESTree.AssignmentExpression,
  accumulator: string,
): ESTree.StringLiteral[] | null {
  if (
    loop.left.type !== "VariableDeclaration" ||
    loop.left.declare ||
    loop.left.kind !== "const" ||
    loop.left.declarations.length !== 1 ||
    loop.right.type !== "ArrayExpression" ||
    loop.right.elements.length < 2
  )
    return null;
  const item = loop.left.declarations[0];
  let statement: Node | undefined = loop.body;
  if (loop.body.type === "BlockStatement") {
    statement = loop.body.body.length === 1 ? loop.body.body[0] : undefined;
  }
  if (
    item?.id.type !== "Identifier" ||
    item.init !== null ||
    item.id.name === accumulator ||
    statement?.type !== "ExpressionStatement" ||
    statement.expression !== assignment ||
    !accumulatesItem(assignment, accumulator, item.id.name)
  )
    return null;
  const elements: ESTree.StringLiteral[] = [];
  for (const element of loop.right.elements) {
    if (element?.type !== "Literal" || typeof element.value !== "string") return null;
    elements.push(element);
  }
  return elements;
}

function accumulatesItem(node: ESTree.AssignmentExpression, accumulator: string, item: string): boolean {
  if (!named(node.left, accumulator)) return false;
  if (node.operator === "+=") return named(node.right, item);
  if (node.operator !== "=") return false;
  const expression = node.right;
  if (expression.type === "BinaryExpression" && expression.operator === "+") {
    return named(expression.left, accumulator) && named(expression.right, item);
  }
  return (
    expression.type === "TemplateLiteral" &&
    expression.expressions.length === 2 &&
    expression.quasis.every((quasi) => quasi.value.cooked === "") &&
    named(expression.expressions[0], accumulator) &&
    named(expression.expressions[1], item)
  );
}

function named(node: Node | undefined, name: string): boolean {
  return node?.type === "Identifier" && node.name === name;
}
