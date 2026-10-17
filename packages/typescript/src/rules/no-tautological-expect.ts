/**
 * @fileoverview no-tautological-expect — supported literal-only assertions that are known to pass.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-tautological-expect.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { directArgumentCall, outerExpression, unwrapExpression } from "./_unwrap-expression.js";
import { runtimeTestFrameworkName } from "./_test-mock-provenance.js";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "tautologicalComparison" | "tautologicalMatcher";
type Options = readonly [];

export const NO_TAUTOLOGICAL_EXPECT_DOCUMENTATION = {
  summary:
    "Disallow supported assertions fixed by literal setup or immutable self identity.",
  rationale:
    "An assertion fixed by literal setup or one immutable binding's identity cannot distinguish a wrong result from the intended behavior.",
  remediation: "Assert on a value produced by the behavior under test against an independently specified expectation, or remove only the redundant assertion while preserving coverage.",
  category: "testing",
  limitations: [
    "Only supported `expect` matcher calls in recognized test files are inspected, including imported aliases, static string messages on imported Vitest/Playwright expect calls, and a single `.not` on zero-argument matchers. Local or type-only bindings, regular expressions, async modifiers and unsupported coercions are excluded; failing constant assertions are not tautologies.",
    "The literal proof resolves scalar const bindings and aliases through lexical scope; mutable bindings, objects, arrays, destructuring, runtime initializers and forward references are excluded from that proof.",
    "Positive toBe assertions on the same initialized, unreassigned local identifier const binding also have fixed identity, including runtime results. Different bindings, imported live values, property/getter accesses and deep-equality reflexivity remain excluded from this identity proof.",
    "Expected-side runtime dependence, including a complete inline snapshot computed from its actual value, remains manual review; independent static interpolation and intentional partial masking are valid.",
    "Direct framework expect.extend registrations exclude replaced built-in matchers; opaque registrations exclude all supported matchers, and nonempty custom equality testers exclude deep equality. Direct synchronous expect callbacks observed by a throwing matcher retain their assertion contracts. Cross-file or indirect matcher customization is not inferred.",
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
      id: "negated-setup-oracle",
      scenarioId: "negated-setup",
      title: "Negating a fixed matcher still does not observe the application",
      outcome: "match",
      files: [{path: "src/service.test.ts", source: "import {expect as verify} from 'vitest'; it('works', () => { const ready = false; verify(ready).not.toBeTruthy(); });"}],
      focusPath: "src/service.test.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "negated-produced-oracle",
      scenarioId: "negated-setup",
      title: "A negated assertion can observe a runtime result",
      outcome: "no-match",
      files: [{path: "src/service.test.ts", source: "import {expect as verify} from 'vitest'; it('works', () => { verify(serviceStatus()).not.toBeNull(); });"}],
      focusPath: "src/service.test.ts",
      expectedCount: 0,
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
    {
      id: "message-only-oracle", scenarioId: "static-message", title: "A diagnostic string does not make a literal comparison observe behavior", outcome: "match",
      files: [{path: "src/service.test.ts", source: "import {expect} from 'vitest'; expect(true, 'service ready').toBe(true);"}], focusPath: "src/service.test.ts", expectedCount: 1, public: true,
    },
    {
      id: "message-produced-oracle", scenarioId: "static-message", title: "A diagnostic message can describe an observed result", outcome: "no-match",
      files: [{path: "src/service.test.ts", source: "import {expect} from 'vitest'; expect(serviceReady(), 'service ready').toBe(true);"}], focusPath: "src/service.test.ts", expectedCount: 0, public: true,
    },
    {
      id: "uncaptured-matcher", scenarioId: "matcher-contract", title: "An uncaptured literal assertion remains redundant", outcome: "match",
      files: [{path: "src/assertion.test.ts", source: "import {expect} from 'vitest'; expect(true).toBeTruthy();"}], focusPath: "src/assertion.test.ts", expectedCount: 1, public: true,
    },
    {
      id: "captured-matcher", scenarioId: "matcher-contract", title: "A throwing matcher observes the inner assertion contract", outcome: "no-match",
      files: [{path: "src/assertion.test.ts", source: "import {expect} from 'vitest'; expect(() => expect(true).toBeTruthy()).not.toThrow();"}], focusPath: "src/assertion.test.ts", expectedCount: 0, public: true,
    },
    {
      id: "unrelated-custom-matcher", scenarioId: "custom-matcher", title: "Adding a different matcher preserves the built-in proof", outcome: "match",
      files: [{path: "src/assertion.test.ts", source: "import {expect} from 'vitest'; expect.extend({toBeReady: custom}); expect(true).toBe(true);"}], focusPath: "src/assertion.test.ts", expectedCount: 1, public: true,
    },
    {
      id: "replaced-custom-matcher", scenarioId: "custom-matcher", title: "A replaced matcher can reject a literal comparison", outcome: "no-match",
      files: [{path: "src/assertion.test.ts", source: "import {expect} from 'vitest'; expect.extend({toBe: () => ({pass: false, message: () => 'custom contract'})}); expect(true).toBe(true);"}], focusPath: "src/assertion.test.ts", expectedCount: 0, public: true,
    },
    {
      id: "self-identity-oracle", scenarioId: "immutable-identity", title: "A returned value's identity with itself cannot reject a wrong result", outcome: "match",
      files: [{path: "src/service.test.ts", source: "import {expect} from 'vitest'; const result = serviceStatus(); expect(result).toBe(result);"}], focusPath: "src/service.test.ts", expectedCount: 1, public: true,
    },
    {
      id: "independent-result-oracle", scenarioId: "immutable-identity", title: "An independent expected state can reject a wrong result", outcome: "no-match",
      files: [{path: "src/service.test.ts", source: "import {expect} from 'vitest'; const result = serviceStatus(); expect(result.status).toBe('ready');"}], focusPath: "src/service.test.ts", expectedCount: 0, public: true,
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
const THROW_MATCHERS: ReadonlySet<string> = new Set(["toThrow", "toThrowError", "toThrowErrorMatchingSnapshot", "toThrowErrorMatchingInlineSnapshot"]);

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

/** Resolve one optional negation; async modifiers do not prove a literal outcome. */
function expectOperand(
  callee: TSESTree.MemberExpression,
  sourceCode: Readonly<TSESLint.SourceCode>,
): { readonly operand: TSESTree.Node; readonly negated: boolean } | null {
  let receiver = unwrapExpression(callee.object);
  const negated = receiver.type === AST_NODE_TYPES.MemberExpression && ASTUtils.getPropertyName(receiver) === "not";
  if (negated && receiver.type === AST_NODE_TYPES.MemberExpression) receiver = unwrapExpression(receiver.object);
  const expectCallee = receiver.type === AST_NODE_TYPES.CallExpression ? unwrapExpression(receiver.callee) : null;
  if (
    receiver.type !== AST_NODE_TYPES.CallExpression ||
    expectCallee?.type !== AST_NODE_TYPES.Identifier ||
    runtimeTestFrameworkName(sourceCode, expectCallee, "assertion") !== "expect" ||
    (receiver.arguments.length !== 1 && !hasStaticMessage(receiver, expectCallee, sourceCode))
  ) {
    return null;
  }
  const operand = receiver.arguments[0];
  return operand === undefined ? null : { operand, negated };
}

function hasStaticMessage(call: TSESTree.CallExpression, callee: TSESTree.Identifier, source: Readonly<TSESLint.SourceCode>): boolean {
  if (call.arguments.length !== 2) return false;
  const definition = ASTUtils.findVariable(source.getScope(callee), callee.name)?.defs[0];
  if (definition?.type !== "ImportBinding" || definition.parent.type !== AST_NODE_TYPES.ImportDeclaration ||
      !["vitest", "@playwright/test"].includes(definition.parent.source.value)) return false;
  const message = call.arguments[1];
  const literal = message === undefined ? null : resolveLiteral(message, source);
  return literal?.type === AST_NODE_TYPES.Literal && typeof literal.value === "string" || literal?.type === AST_NODE_TYPES.TemplateLiteral;
}

function isExceptionContract(node: TSESTree.Node, source: Readonly<TSESLint.SourceCode>): boolean {
  let callback = node.parent;
  while (callback !== undefined && callback.type !== AST_NODE_TYPES.Program && callback.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
      callback.type !== AST_NODE_TYPES.FunctionExpression && callback.type !== AST_NODE_TYPES.FunctionDeclaration) callback = callback.parent;
  if (callback === undefined || callback.type === AST_NODE_TYPES.Program || callback.type === AST_NODE_TYPES.FunctionDeclaration || callback.async || callback.generator) return false;
  const call = directArgumentCall(callback);
  if (call === null || call.optional) return false;
  let member = outerExpression(call).parent;
  if (member?.type === AST_NODE_TYPES.MemberExpression && ASTUtils.getPropertyName(member) === "not") member = outerExpression(member).parent;
  if (member?.type !== AST_NODE_TYPES.MemberExpression || member.optional || !THROW_MATCHERS.has(ASTUtils.getPropertyName(member) ?? "")) return false;
  const invocation = outerExpression(member).parent;
  return invocation?.type === AST_NODE_TYPES.CallExpression && !invocation.optional &&
    unwrapExpression(expectOperand(member, source)?.operand ?? member) === callback;
}

function customizedMatchers(source: Readonly<TSESLint.SourceCode>): ReadonlySet<string> {
  const customized = new Set<string>();
  const visit = (node: TSESTree.Node): void => {
    if (node.type === AST_NODE_TYPES.CallExpression) collectCustomization(node, source, customized);
    for (const key of source.visitorKeys[node.type] ?? []) {
      const child = (node as unknown as Record<string, unknown>)[key];
      for (const value of Array.isArray(child) ? child : [child]) {
        if (typeof value === "object" && value !== null && "type" in value) visit(value as TSESTree.Node);
      }
    }
  };
  visit(source.ast);
  return customized;
}

function collectCustomization(node: TSESTree.CallExpression, source: Readonly<TSESLint.SourceCode>, customized: Set<string>): void {
  const member = unwrapExpression(node.callee);
  if (member.type !== AST_NODE_TYPES.MemberExpression) return;
  const receiver = unwrapExpression(member.object);
  if (receiver.type !== AST_NODE_TYPES.Identifier || runtimeTestFrameworkName(source, receiver, "assertion") !== "expect") return;
  const method = ASTUtils.getPropertyName(member);
  const argument = node.arguments[0] === undefined ? null : unwrapExpression(node.arguments[0]);
  if (method === "addEqualityTesters" && !(argument?.type === AST_NODE_TYPES.ArrayExpression && argument.elements.length === 0)) {
    customized.add("toEqual");
    customized.add("toStrictEqual");
  }
  if (method !== "extend") return;
  if (argument?.type !== AST_NODE_TYPES.ObjectExpression) {
    customized.add("*");
    return;
  }
  for (const property of argument.properties) {
    const name = property.type === AST_NODE_TYPES.Property ? ASTUtils.getPropertyName(property) : null;
    customized.add(name ?? "*");
  }
}

function hasConstSelfIdentity(actual: TSESTree.Node, expected: TSESTree.Node, source: Readonly<TSESLint.SourceCode>): boolean {
  actual = unwrapExpression(actual);
  expected = unwrapExpression(expected);
  if (actual.type !== AST_NODE_TYPES.Identifier || expected.type !== AST_NODE_TYPES.Identifier) return false;
  const variable = ASTUtils.findVariable(source.getScope(actual), actual.name);
  if (variable?.defs.length !== 1 || ASTUtils.findVariable(source.getScope(expected), expected.name) !== variable) return false;
  const definition = variable.defs[0];
  return definition?.node.type === AST_NODE_TYPES.VariableDeclarator &&
    definition.node.id.type === AST_NODE_TYPES.Identifier && definition.node.parent.kind === "const" &&
    definition.node.init !== null && definition.node.init.range[1] <= Math.min(actual.range[0], expected.range[0]) &&
    !variable.references.some(reference => reference.isWrite() && !reference.init);
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
        "`expect({{operand}}).{{matcher}}({{operand}})` is fixed by {{reason}} and does not observe behavior. Assert against an independent expectation or remove only the redundant assertion, preserving the action and other coverage.",
      tautologicalMatcher:
        "`expect({{operand}}).{{matcher}}()` is statically known to pass. Assert on a produced value or remove only the redundant assertion, preserving other coverage.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename)) {
      return {};
    }
    const customized = customizedMatchers(context.sourceCode);
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
        if (matcher === null || (!ZERO_ARG_MATCHERS.has(matcher) && !EQUALITY_MATCHERS.has(matcher)) ||
            customized.has("*") || customized.has(matcher)) return;
        const assertion = expectOperand(callee, context.sourceCode);
        if (assertion === null || isExceptionContract(node, context.sourceCode)) return;
        const writtenOperand = assertion.operand;
        const writtenExpected = node.arguments[0];
        if (!assertion.negated && matcher === "toBe" && node.arguments.length === 1 && writtenExpected !== undefined &&
            hasConstSelfIdentity(writtenOperand, writtenExpected, context.sourceCode)) {
          context.report({
            node, messageId: "tautologicalComparison", data: {operand: preview(writtenOperand), matcher, reason: "the same immutable binding"},
          });
          return;
        }
        const operand = resolveLiteral(writtenOperand, context.sourceCode);
        if (operand === null) {
          return;
        }
        const writtenMatcher = `${assertion.negated ? "not." : ""}${matcher}`;
        if (ZERO_ARG_MATCHERS.has(matcher) && node.arguments.length === 0 && passesZeroArgumentMatcher(operand, matcher) !== assertion.negated) {
          context.report({
            node,
            messageId: "tautologicalMatcher",
            data: { operand: preview(writtenOperand), matcher: writtenMatcher },
          });
          return;
        }
        const expected = writtenExpected === undefined ? null : resolveLiteral(writtenExpected, context.sourceCode);
        if (
          assertion.negated || !EQUALITY_MATCHERS.has(matcher) ||
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
          data: { operand: preview(writtenOperand), matcher, reason: "literal setup" },
        });
      },
    };
  },
});
