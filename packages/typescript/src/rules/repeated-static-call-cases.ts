/**
 * @fileoverview repeated-static-call-cases — repeated literal call assertions should be named, independently reported cases.
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/repeated-static-call-cases.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { duplicateTestBodyCandidate } from "./duplicate-test-body.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "repeatedStaticCallCases";
type Options = readonly [];
type Context = Readonly<TSESLint.RuleContext<MessageIds, Options>>;

export const repeatedStaticCallCasesDocumentation = {
  summary: "Report three or more consecutive literal call assertions that should be independently named test cases.",
  rationale: "Copy-pasted cases obscure the input table and stop later cases from being reported after the first failure.",
  remediation: "Replace the repeated assertions with a named `test.each` or `it.each` table.",
  category: "testing",
  filePatterns: ["**/*.test.*", "**/*.spec.*", "**/tests/**", "**/__tests__/**"],
  limitations: ["Only consecutive top-level assertions with direct calls and entirely static inputs and expected values are reported."],
  examples: [
    { id: "parameterized", title: "Name each case", outcome: "no-match", files: [{ path: "src/parser.test.ts", source: "test.each([['a', true], ['b', false], ['c', true]])('parses %s', (input, expected) => { expect(parse(input)).toBe(expected); });" }], focusPath: "src/parser.test.ts", expectedCount: 0, public: true },
    { id: "repeated", title: "Do not repeat literal cases", outcome: "match", files: [{ path: "src/parser.test.ts", source: "test('parses', () => { expect(parse('a')).toBe(true); expect(parse('b')).toBe(false); expect(parse('c')).toBe(true); });" }], focusPath: "src/parser.test.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const TEST_MODULES: ReadonlySet<string> = new Set(["@jest/globals", "@playwright/test", "bun:test", "node:test", "vitest"]);
const ASSERTION_MODULES: ReadonlySet<string> = new Set([...TEST_MODULES]);
const TEST_NAMES: ReadonlySet<string> = new Set(["it", "test"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["concurrent", "fails", "only", "sequential", "skip"]);
const EXPECT_MODIFIERS: ReadonlySet<string> = new Set(["not", "rejects", "resolves"]);
const SNAPSHOT_MATCHERS = /snapshot/iu;
const MIN_CASES = 3;

type FunctionNode = TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression;

interface AssertionShape {
  statement: TSESTree.ExpressionStatement;
  skeleton: string;
  values: string;
}

interface PendingFinding {
  readonly callback: FunctionNode;
  readonly count: number;
  readonly statement: TSESTree.ExpressionStatement;
}

function staticMemberName(node: TSESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier) return node.property.name;
  if (node.computed && node.property.type === AST_NODE_TYPES.Literal && typeof node.property.value === "string") return node.property.value;
  return null;
}

function importedName(identifier: TSESTree.Identifier, context: Context, modules: ReadonlySet<string>): string | null {
  const variable = ASTUtils.findVariable(context.sourceCode.getScope(identifier), identifier.name);
  if (variable === null || variable.defs.length === 0) return identifier.name;
  for (const definition of variable.defs) {
    if (definition.node.type !== AST_NODE_TYPES.ImportSpecifier) continue;
    const declaration = definition.node.parent;
    if (declaration.type !== AST_NODE_TYPES.ImportDeclaration || typeof declaration.source.value !== "string" || !modules.has(declaration.source.value)) continue;
    const imported = definition.node.imported;
    return imported.type === AST_NODE_TYPES.Identifier ? imported.name : String(imported.value);
  }
  return null;
}

function isDirectTestCallback(node: TSESTree.Node, context: Context): node is FunctionNode {
  if (node.type !== AST_NODE_TYPES.ArrowFunctionExpression && node.type !== AST_NODE_TYPES.FunctionExpression) return false;
  const call = node.parent;
  if (call?.type !== AST_NODE_TYPES.CallExpression || !call.arguments.includes(node)) return false;
  const root = testRoot(call.callee);
  return root !== null && TEST_NAMES.has(importedName(root, context, TEST_MODULES) ?? "");
}

function testRoot(callee: TSESTree.Node): TSESTree.Identifier | null {
  if (callee.type === AST_NODE_TYPES.Identifier) return callee;
  if (callee.type !== AST_NODE_TYPES.MemberExpression) return null;
  const modifier = staticMemberName(callee);
  return modifier !== null && TEST_MODIFIERS.has(modifier) ? testRoot(callee.object) : null;
}

function isStatic(node: TSESTree.Node): boolean {
  if (node.type === AST_NODE_TYPES.TSAsExpression || node.type === AST_NODE_TYPES.TSTypeAssertion || node.type === AST_NODE_TYPES.TSSatisfiesExpression || node.type === AST_NODE_TYPES.TSNonNullExpression) return isStatic(node.expression);
  switch (node.type) {
    case AST_NODE_TYPES.Literal: return true;
    case AST_NODE_TYPES.TemplateLiteral: return node.expressions.length === 0;
    case AST_NODE_TYPES.UnaryExpression: return (node.operator === "+" || node.operator === "-") && isStatic(node.argument);
    case AST_NODE_TYPES.ArrayExpression: return node.elements.every((item) => item !== null && item.type !== AST_NODE_TYPES.SpreadElement && isStatic(item));
    case AST_NODE_TYPES.ObjectExpression: return node.properties.every((property) => property.type === AST_NODE_TYPES.Property && !property.computed && property.kind === "init" && property.value.type !== AST_NODE_TYPES.AssignmentPattern && isStatic(property.value));
    default: return false;
  }
}

/** Preserve literal container/operator structure while replacing the values. */
function staticShape(node: TSESTree.Node): string {
  if (node.type === AST_NODE_TYPES.TSAsExpression || node.type === AST_NODE_TYPES.TSTypeAssertion || node.type === AST_NODE_TYPES.TSSatisfiesExpression || node.type === AST_NODE_TYPES.TSNonNullExpression) return staticShape(node.expression);
  switch (node.type) {
    case AST_NODE_TYPES.Literal: return `literal:${typeof node.value}`;
    case AST_NODE_TYPES.TemplateLiteral: return "template";
    case AST_NODE_TYPES.UnaryExpression: return `unary:${node.operator}:${staticShape(node.argument)}`;
    case AST_NODE_TYPES.ArrayExpression: return `array(${node.elements.map((item) => item === null || item.type === AST_NODE_TYPES.SpreadElement ? "invalid" : staticShape(item)).join(",")})`;
    case AST_NODE_TYPES.ObjectExpression:
      return `object(${node.properties.map((property) => {
        if (property.type !== AST_NODE_TYPES.Property || property.computed || property.value.type === AST_NODE_TYPES.AssignmentPattern) return "invalid";
        const key = property.key.type === AST_NODE_TYPES.Identifier ? property.key.name : String(property.key.value);
        return `${key}:${staticShape(property.value)}`;
      }).join(",")})`;
    default: return "dynamic";
  }
}

function assertionShape(statement: TSESTree.Statement, context: Context): AssertionShape | null {
  if (statement.type !== AST_NODE_TYPES.ExpressionStatement || statement.expression.type !== AST_NODE_TYPES.CallExpression) return null;
  const matcherCall = statement.expression;
  if (matcherCall.callee.type !== AST_NODE_TYPES.MemberExpression || matcherCall.callee.computed || matcherCall.callee.property.type !== AST_NODE_TYPES.Identifier || matcherCall.arguments.length !== 1) return null;
  const matcher = matcherCall.callee.property.name;
  if (SNAPSHOT_MATCHERS.test(matcher)) return null;
  const chain = expectCallFromMatcher(matcherCall.callee);
  if (chain === null || chain.call.callee.type !== AST_NODE_TYPES.Identifier || importedName(chain.call.callee, context, ASSERTION_MODULES) !== "expect" || chain.call.arguments.length !== 1) return null;
  const observed = chain.call.arguments[0];
  const expected = matcherCall.arguments[0];
  if (observed?.type !== AST_NODE_TYPES.CallExpression || observed.callee.type !== AST_NODE_TYPES.Identifier || observed.arguments.length === 0 || observed.arguments.some((arg) => arg.type === AST_NODE_TYPES.SpreadElement || !isStatic(arg)) || expected?.type === AST_NODE_TYPES.SpreadElement || expected === undefined || !isStatic(expected)) return null;
  const skeleton = `${observed.callee.name}/${observed.arguments.map((item) => staticShape(item)).join(",")}/${chain.modifiers.join(".")}/${matcher}/${staticShape(expected)}`;
  const values = [...observed.arguments, expected].map((item) => context.sourceCode.getText(item)).join("\u0000");
  return { statement, skeleton, values };
}

function expectCallFromMatcher(node: TSESTree.MemberExpression): { call: TSESTree.CallExpression; modifiers: string[] } | null {
  const modifiers: string[] = [];
  let receiver: TSESTree.Expression = node.object;
  while (receiver.type === AST_NODE_TYPES.MemberExpression) {
    const modifier = staticMemberName(receiver);
    if (modifier === null || !EXPECT_MODIFIERS.has(modifier)) return null;
    modifiers.unshift(modifier);
    receiver = receiver.object;
  }
  return receiver.type === AST_NODE_TYPES.CallExpression ? { call: receiver, modifiers } : null;
}

export default createRule<Options, MessageIds>({
  name: "repeated-static-call-cases",
  documentation: repeatedStaticCallCasesDocumentation,
  meta: {
    type: "suggestion",
    docs: { description: "Report three or more consecutive literal call assertions that should be independently named test cases." },
    schema: [],
    messages: { repeatedStaticCallCases: "These {{count}} consecutive assertions repeat the same call with static cases. Use a named `test.each` or `it.each` table so every case is independently reported." },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    if (!isTestFile(context.filename) || isGeneratedFile(context.filename, sourceCode.text)) return {};
    const duplicateGroups = new Map<TSESTree.Node, Map<string, FunctionNode[]>>();
    const pending: PendingFinding[] = [];
    return {
      "CallExpression > ArrowFunctionExpression, CallExpression > FunctionExpression"(node: FunctionNode): void {
        const call = node.parent;
        if (call?.type === AST_NODE_TYPES.CallExpression) {
          const duplicate = duplicateTestBodyCandidate(call, sourceCode);
          if (duplicate !== null && duplicate.body === node) {
            const groups = duplicateGroups.get(duplicate.container) ?? new Map<string, FunctionNode[]>();
            const owners = groups.get(duplicate.fingerprint) ?? [];
            owners.push(node);
            groups.set(duplicate.fingerprint, owners);
            duplicateGroups.set(duplicate.container, groups);
          }
        }
        if (!isDirectTestCallback(node, context) || node.body.type !== AST_NODE_TYPES.BlockStatement) return;
        let run: AssertionShape[] = [];
        const flush = (): void => {
          if (run.length >= MIN_CASES && new Set(run.map((item) => item.values)).size > 1) {
            const first = run[0];
            const last = run.at(-1);
            const hasComment = first !== undefined && last !== undefined && sourceCode.getAllComments().some((comment) => comment.range[0] >= first.statement.range[0] && comment.range[1] <= last.statement.range[1]);
            if (first !== undefined && last !== undefined && !hasComment) {
              pending.push({ callback: node, count: run.length, statement: first.statement });
            }
          }
          run = [];
        };
        for (const statement of node.body.body) {
          const shape = assertionShape(statement, context);
          if (shape === null || (run.length > 0 && run[0]?.skeleton !== shape.skeleton)) flush();
          if (shape !== null) run.push(shape);
        }
        flush();
      },
      "Program:exit"(): void {
        const duplicateOwners = new Set<FunctionNode>();
        for (const groups of duplicateGroups.values()) {
          for (const owners of groups.values()) {
            if (owners.length > 1) owners.forEach((owner) => duplicateOwners.add(owner));
          }
        }
        for (const finding of pending) {
          if (duplicateOwners.has(finding.callback)) continue;
          context.report({
            node: finding.statement,
            messageId: "repeatedStaticCallCases",
            data: { count: String(finding.count) },
          });
        }
      },
    };
  },
});
