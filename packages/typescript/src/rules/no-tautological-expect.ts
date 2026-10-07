/**
 * @fileoverview no-tautological-expect — supported literal-only assertions that are known to pass.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-tautological-expect.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { unwrapExpression } from "./_unwrap-expression.js";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "tautologicalComparison" | "tautologicalMatcher";
type Options = readonly [];

export const NO_TAUTOLOGICAL_EXPECT_DOCUMENTATION = {
  summary:
    "Disallow supported assertions known to pass from literals or immutable scalar setup.",
  rationale:
    "An assertion determined entirely by literals does not observe the code under test and can keep passing after that code is removed.",
  remediation: "Assert on a value produced by the behavior under test, or remove the assertion.",
  category: "testing",
  limitations: [
    "Only direct supported `expect` matcher calls in recognized test files are inspected. Local expect bindings, regular expressions, and unsupported coercions are excluded; failing constant assertions are not tautologies.",
    "Scalar const bindings and aliases resolve through lexical scope; mutable bindings, objects, arrays, destructuring, runtime initializers and forward references are excluded.",
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
    {
      id: "setup-only-oracle",
      scenarioId: "setup-only",
      title: "A const setup assertion never observes the application",
      outcome: "match",
      files: [{path: "src/service.test.ts", source: "it('works', () => { const status = 'ok'; expect(status).toBe('ok'); });"}],
      focusPath: "src/service.test.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "produced-scalar-oracle",
      scenarioId: "setup-only",
      title: "A runtime scalar result remains a valid observation",
      outcome: "no-match",
      files: [{path: "src/service.test.ts", source: "it('works', () => { const status = serviceStatus(); expect(status).toBe('ok'); });"}],
      focusPath: "src/service.test.ts",
      expectedCount: 0,
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

function resolveLiteral(
  node: TSESTree.Node,
  sourceCode: Readonly<TSESLint.SourceCode>,
  seen: Set<TSESTree.Node> = new Set(),
): TSESTree.Node | null {
  node = unwrapExpression(node);
  if (isLiteral(node)) return node;
  if (node.type !== AST_NODE_TYPES.Identifier || seen.has(node)) return null;
  seen.add(node);
  const variable = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
  if (variable?.defs.length !== 1) return null;
  const definition = variable.defs[0];
  if (definition?.node.type !== AST_NODE_TYPES.VariableDeclarator ||
      definition.node.id.type !== AST_NODE_TYPES.Identifier ||
      definition.node.parent.kind !== "const" || definition.node.init === null ||
      definition.node.init.range[1] > node.range[0] ||
      variable.references.some((reference) => reference.isWrite() && !reference.init)) return null;
  const value = resolveLiteral(definition.node.init, sourceCode, seen);
  return value !== null && !isStructuralLiteral(value) ? value : null;
}

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
  const receiver = unwrapExpression(callee.object);
  const expectCallee = receiver.type === AST_NODE_TYPES.CallExpression ? unwrapExpression(receiver.callee) : null;
  if (
    receiver.type !== AST_NODE_TYPES.CallExpression ||
    expectCallee?.type !== AST_NODE_TYPES.Identifier ||
    expectCallee.name !== "expect" ||
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
        NO_TAUTOLOGICAL_EXPECT_DOCUMENTATION.summary,
    },
    schema: [],
    messages: {
      tautologicalComparison:
        "`expect({{operand}}).{{matcher}}({{operand}})` is fixed by literal setup and does not observe behavior. Assert on a produced value or remove only the redundant assertion, preserving other coverage.",
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
        const callee = unwrapExpression(node.callee);

        if (callee.type !== AST_NODE_TYPES.MemberExpression) return;
        const matcher = ASTUtils.getPropertyName(callee);
        if (matcher === null) return;
        const receiver = unwrapExpression(callee.object);
        if (receiver.type !== AST_NODE_TYPES.CallExpression) return;
        const expectIdentifier = unwrapExpression(receiver.callee);
        if (expectIdentifier.type !== AST_NODE_TYPES.Identifier) return;
        const variable = ASTUtils.findVariable(context.sourceCode.getScope(expectIdentifier), expectIdentifier.name);
        if (variable !== null && variable.defs.some((definition) => {
          if (definition.node.type !== AST_NODE_TYPES.ImportSpecifier) return true;
          const declaration = definition.node.parent;
          const imported = definition.node.imported;
          return declaration.type !== AST_NODE_TYPES.ImportDeclaration ||
            !["vitest", "@jest/globals", "@playwright/test", "bun:test"].includes(String(declaration.source.value)) ||
            (imported.type === AST_NODE_TYPES.Identifier ? imported.name : imported.value) !== "expect";
        })) return;
        const writtenOperand = expectOperand(callee);
        const operand = writtenOperand === null ? null : resolveLiteral(writtenOperand, context.sourceCode);
        if (operand === null) {
          return;
        }
        if (ZERO_ARG_MATCHERS.has(matcher) && node.arguments.length === 0 && passesZeroArgumentMatcher(operand, matcher)) {
          context.report({
            node,
            messageId: "tautologicalMatcher",
            data: { operand: preview(writtenOperand ?? operand), matcher },
          });
          return;
        }
        const writtenExpected = node.arguments[0];
        const expected = writtenExpected === undefined ? null : resolveLiteral(writtenExpected, context.sourceCode);
        if (
          !EQUALITY_MATCHERS.has(matcher) ||
          node.arguments.length !== 1 ||
          expected === null
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
          data: { operand: preview(writtenOperand ?? operand), matcher },
        });
      },
    };
  },
});
