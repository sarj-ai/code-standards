/**
 * @fileoverview no-tautological-expect — supported literal-only assertions that are known to pass.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-tautological-expect.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "tautologicalComparison" | "tautologicalMatcher";
type Options = readonly [];

export const NO_TAUTOLOGICAL_EXPECT_DOCUMENTATION = {
  summary:
    "Disallow supported literal-only assertions that are statically known to pass.",
  rationale:
    "An assertion determined entirely by literals does not observe the code under test and can keep passing after that code is removed.",
  remediation: "Assert on a value produced by the behavior under test, or remove the assertion.",
  category: "testing",
  limitations: [
    "Only direct supported `expect` matcher calls in recognized test files are inspected. Local expect bindings, regular expressions, and unsupported coercions are excluded; failing constant assertions are not tautologies.",
  ],
  examples: [
    {
      id: "produced-value",
      title: "Assert on a produced value",
      outcome: "no-match",
      files: [{ path: "src/add.test.ts", source: "it('adds', () => { expect(add(1, 1)).toBe(2); });" }],
      focusPath: "src/add.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "literal-only-assertion",
      title: "Do not compare identical literals",
      outcome: "match",
      files: [{ path: "src/add.test.ts", source: "it('works', () => { expect(true).toBe(true); });" }],
      focusPath: "src/add.test.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

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
      return !("regex" in node);
    case AST_NODE_TYPES.TemplateLiteral:
      return node.expressions.length === 0;
    case AST_NODE_TYPES.UnaryExpression:
      return NUMERIC_SIGNS.has(node.operator) && node.argument.type === AST_NODE_TYPES.Literal && typeof node.argument.value === "number";
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

function isStructuralLiteral(node: TSESTree.Node): boolean {
  return node.type === AST_NODE_TYPES.ArrayExpression || node.type === AST_NODE_TYPES.ObjectExpression;
}

function passesZeroArgumentMatcher(node: TSESTree.Node, matcher: string): boolean {
  let value: unknown;
  switch (node.type) {
    case AST_NODE_TYPES.Literal: value = node.value; break;
    case AST_NODE_TYPES.TemplateLiteral: value = node.quasis[0]?.value.cooked; break;
    case AST_NODE_TYPES.UnaryExpression:
      if (node.argument.type !== AST_NODE_TYPES.Literal || typeof node.argument.value !== "number") return false;
      value = node.operator === "-" ? -node.argument.value : node.argument.value;
      break;
    case AST_NODE_TYPES.ArrayExpression:
    case AST_NODE_TYPES.ObjectExpression: value = {}; break;
    default: return false;
  }
  switch (matcher) {
    case "toBeDefined": return value !== undefined;
    case "toBeUndefined": return value === undefined;
    case "toBeNull": return value === null;
    case "toBeTruthy": return Boolean(value);
    case "toBeFalsy": return !value;
    case "toBeNaN": return typeof value === "number" && Number.isNaN(value);
    default: return false;
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
  documentation: NO_TAUTOLOGICAL_EXPECT_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow supported literal-only assertions that are statically known to pass.",
    },
    schema: [],
    messages: {
      tautologicalComparison:
        "`expect({{operand}}).{{matcher}}({{operand}})` compares an identical literal and does not observe behavior. Assert on a produced value or remove only the redundant assertion, preserving other coverage.",
      tautologicalMatcher:
        "`expect({{operand}}).{{matcher}}()` is statically known to pass. Assert on a produced value or remove only the redundant assertion, preserving other coverage.",
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
        if (callee.object.type !== AST_NODE_TYPES.CallExpression || callee.object.callee.type !== AST_NODE_TYPES.Identifier) return;
        const expectIdentifier = callee.object.callee;
        const variable = ASTUtils.findVariable(context.sourceCode.getScope(expectIdentifier), expectIdentifier.name);
        if (variable !== null && variable.defs.some((definition) => {
          if (definition.node.type !== AST_NODE_TYPES.ImportSpecifier) return true;
          const declaration = definition.node.parent;
          const imported = definition.node.imported;
          return declaration.type !== AST_NODE_TYPES.ImportDeclaration ||
            !["vitest", "@jest/globals", "@playwright/test", "bun:test"].includes(String(declaration.source.value)) ||
            (imported.type === AST_NODE_TYPES.Identifier ? imported.name : imported.value) !== "expect";
        })) return;
        const operand = expectOperand(callee);
        if (operand === null || !isLiteral(operand)) {
          return;
        }
        if (ZERO_ARG_MATCHERS.has(matcher) && node.arguments.length === 0 && passesZeroArgumentMatcher(operand, matcher)) {
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
        if (matcher === "toBe" && (isStructuralLiteral(operand) || isStructuralLiteral(expected))) {
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
