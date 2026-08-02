/**
 * @fileoverview no-tautological-expect — an assertion whose operands are all literals decided its outcome before the code ran, so it can never fail.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-tautological-expect.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "tautologicalComparison" | "tautologicalMatcher";
type Options = readonly [];

/** Matchers that take the expected value as their single argument. */
const EQUALITY_MATCHERS: ReadonlySet<string> = new Set(["toBe", "toEqual", "toStrictEqual"]);

/** Matchers that take no argument, so the receiver alone fixes the outcome. */
const ZERO_ARG_MATCHERS: ReadonlySet<string> = new Set([
  "toBeDefined",
  "toBeUndefined",
  "toBeNull",
  "toBeTruthy",
  "toBeFalsy",
  "toBeNaN",
]);

/** Enough of the operand to identify it in the message without pasting a screenful. */
const OPERAND_PREVIEW_CHARS = 40;

/** Sign prefixes: `-1` is a unary expression, not a literal, but it is constant. */
const NUMERIC_SIGNS: ReadonlySet<string> = new Set(["-", "+"]);

function isLiteral(node: TSESTree.Node): boolean {
  switch (node.type) {
    case AST_NODE_TYPES.Literal:
      return true;
    case AST_NODE_TYPES.TemplateLiteral:
      return node.expressions.length === 0;
    case AST_NODE_TYPES.UnaryExpression:
      return NUMERIC_SIGNS.has(node.operator) && isLiteral(node.argument);
    case AST_NODE_TYPES.ArrayExpression:
      return node.elements.every((element) => element !== null && isLiteral(element));
    case AST_NODE_TYPES.ObjectExpression:
      return node.properties.every(
        (property) =>
          property.type === AST_NODE_TYPES.Property &&
          !property.computed &&
          isLiteral(property.value),
      );
    default:
      return false;
  }
}

/** The `expect(<single argument>)` call a matcher hangs directly off, if any. */
function expectOperand(callee: TSESTree.MemberExpression): TSESTree.Node | null {
  const receiver = callee.object;
  if (
    receiver.type !== AST_NODE_TYPES.CallExpression ||
    receiver.callee.type !== AST_NODE_TYPES.Identifier ||
    receiver.callee.name !== "expect" ||
    receiver.arguments.length !== 1
  ) {
    return null;
  }
  return receiver.arguments[0] ?? null;
}

export default createRule<Options, MessageIds>({
  name: "no-tautological-expect",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow an assertion whose operands are all literals; its outcome is fixed before the code runs, so it can never fail.",
    },
    schema: [],
    messages: {
      tautologicalComparison:
        "`expect({{operand}}).{{matcher}}({{operand}})` compares a literal with an identical literal — it passes even if the code under test is deleted. Assert on a value the code produced, or delete the test.",
      tautologicalMatcher:
        "`expect({{operand}}).{{matcher}}()` asserts on a literal, so its outcome is fixed before the code runs. Assert on a value the code produced, or delete the test.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename)) {
      return {};
    }
    /** The operand as written, collapsed to one line and elided for the message. */
    const preview = (node: TSESTree.Node): string => {
      const text = context.sourceCode.getText(node).replaceAll(/\s+/gu, " ");
      return text.length > OPERAND_PREVIEW_CHARS
        ? `${text.slice(0, OPERAND_PREVIEW_CHARS)}…`
        : text;
    };
    return {
      CallExpression(node: TSESTree.CallExpression): void {
        const callee = node.callee;
        if (callee.type !== AST_NODE_TYPES.MemberExpression || callee.computed) {
          return;
        }
        if (callee.property.type !== AST_NODE_TYPES.Identifier) {
          return;
        }
        const matcher = callee.property.name;
        const operand = expectOperand(callee);
        if (operand === null || !isLiteral(operand)) {
          return;
        }
        if (ZERO_ARG_MATCHERS.has(matcher) && node.arguments.length === 0) {
          context.report({
            node,
            messageId: "tautologicalMatcher",
            data: { operand: preview(operand), matcher },
          });
          return;
        }
        const expected = node.arguments[0];
        if (
          !EQUALITY_MATCHERS.has(matcher) ||
          node.arguments.length !== 1 ||
          expected === undefined ||
          !isLiteral(expected)
        ) {
          return;
        }
        // Textual identity, not structural: `expect(1).toBe(1.0)` is a
        // deliberate statement about representation and is left alone.
        if (context.sourceCode.getText(operand) !== context.sourceCode.getText(expected)) {
          return;
        }
        context.report({
          node,
          messageId: "tautologicalComparison",
          data: { operand: preview(operand), matcher },
        });
      },
    };
  },
});
