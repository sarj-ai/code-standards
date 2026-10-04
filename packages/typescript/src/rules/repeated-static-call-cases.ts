/**
 * @fileoverview repeated-static-call-cases — repeated literal call assertions should be named, independently reported cases.
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/repeated-static-call-cases.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Context } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { duplicateTestBodyCandidate } from "./duplicate-test-body.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "repeatedStaticCallCases";
type Options = readonly [];

export const REPEATED_STATIC_CALL_CASES_DOCUMENTATION = {
  summary:
    "Review three or more consecutive static-input call assertions as potential named cases.",
  rationale:
    "Copy-pasted cases obscure the input table, and a thrown assertion can stop later cases from being reported.",
  remediation:
    "If the calls are independent, use the runner's named parameterized cases or subtests. Preserve ordered state-transition scenarios as one test.",
  category: "testing",
  filePatterns: [
    "**/*.test.*",
    "**/*.spec.*",
    "**/tests/**",
    "**/__tests__/**",
  ],
  limitations: [
    "Only consecutive top-level assertions with direct calls and static inputs and expected values are checked. Test-local callees and fixtures are excluded; imported or outer functions can still be stateful, so manual independence review is required. Not every runner supports test.each.",
  ],
  examples: [
    {
      id: "parameterized",
      title: "Name each case",
      outcome: "no-match",
      files: [
        {
          path: "src/parser.test.ts",
          source:
            "test.each([['a', true], ['b', false], ['c', true]])('parses %s', (input, expected) => { expect(parse(input)).toBe(expected); });",
        },
      ],
      focusPath: "src/parser.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "repeated",
      title: "Do not repeat literal cases",
      outcome: "match",
      files: [
        {
          path: "src/parser.test.ts",
          source:
            "test('parses', () => { expect(parse('a')).toBe(true); expect(parse('b')).toBe(false); expect(parse('c')).toBe(true); });",
        },
      ],
      focusPath: "src/parser.test.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const TEST_MODULES: ReadonlySet<string> = new Set([
  "@jest/globals",
  "@playwright/test",
  "bun:test",
  "node:test",
  "vitest",
]);
const ASSERTION_MODULES: ReadonlySet<string> = new Set([...TEST_MODULES]);
const TEST_NAMES: ReadonlySet<string> = new Set(["it", "test"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set([
  "concurrent",
  "fails",
  "only",
  "sequential",
  "skip",
]);
const EXPECT_MODIFIERS: ReadonlySet<string> = new Set([
  "not",
  "rejects",
  "resolves",
]);
const SNAPSHOT_MATCHERS = /snapshot/iu;
const MIN_CASES = 3;

type FunctionNode = ESTree.ArrowFunctionExpression | ESTree.Function;

interface AssertionShape {
  statement: ESTree.ExpressionStatement;
  skeleton: string;
  values: string;
}

interface PendingFinding {
  readonly callback: FunctionNode;
  readonly count: number;
  readonly statement: ESTree.ExpressionStatement;
}

function staticMemberName(node: ESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === "Identifier")
    return node.property.name;
  if (
    node.computed &&
    node.property.type === "Literal" &&
    typeof node.property.value === "string"
  )
    return node.property.value;
  return null;
}

function importedName(
  identifier: ESTree.BindingIdentifier,
  context: Context,
  modules: ReadonlySet<string>,
): string | null {
  const variable = findVariable(
    context.sourceCode.getScope(identifier),
    identifier.name,
  );
  if (variable === null || variable.defs.length === 0) return identifier.name;
  for (const definition of variable.defs) {
    if (definition.node.type !== "ImportSpecifier") continue;
    const declaration = definition.node.parent;
    if (
      declaration.type !== "ImportDeclaration" ||
      typeof declaration.source.value !== "string" ||
      !modules.has(declaration.source.value)
    )
      continue;
    const imported = definition.node.imported;
    return imported.type === "Identifier"
      ? imported.name
      : String(imported.value);
  }
  return null;
}

function isDirectTestCallback(
  node: ESTree.Node,
  context: Context,
): node is FunctionNode {
  if (
    node.type !== "ArrowFunctionExpression" &&
    node.type !== "FunctionExpression"
  )
    return false;
  const call = node.parent;
  if (call?.type !== "CallExpression" || !call.arguments.includes(node))
    return false;
  const root = testRoot(call.callee);
  return (
    root !== null &&
    TEST_NAMES.has(importedName(root, context, TEST_MODULES) ?? "")
  );
}

function testRoot(callee: ESTree.Node): ESTree.BindingIdentifier | null {
  if (callee.type === "Identifier") return callee;
  if (callee.type !== "MemberExpression") return null;
  const modifier = staticMemberName(callee);
  return modifier !== null && TEST_MODIFIERS.has(modifier)
    ? testRoot(callee.object)
    : null;
}

function isStatic(node: ESTree.Node): boolean {
  if (
    node.type === "TSAsExpression" ||
    node.type === "TSTypeAssertion" ||
    node.type === "TSSatisfiesExpression" ||
    node.type === "TSNonNullExpression"
  )
    return isStatic(node.expression);
  switch (node.type) {
    case "Literal":
      return true;
    case "TemplateLiteral":
      return node.expressions.length === 0;
    case "UnaryExpression":
      return (
        (node.operator === "+" || node.operator === "-") &&
        isStatic(node.argument)
      );
    case "ArrayExpression":
      return node.elements.every(
        (item) =>
          item !== null && item.type !== "SpreadElement" && isStatic(item),
      );
    case "ObjectExpression":
      return node.properties.every(
        (property) =>
          property.type === "Property" &&
          !property.computed &&
          property.kind === "init" &&
          isStatic(property.value),
      );
    default:
      return false;
  }
}

/** Preserve literal container/operator structure while replacing the values. */
function staticShape(node: ESTree.Node): string {
  if (
    node.type === "TSAsExpression" ||
    node.type === "TSTypeAssertion" ||
    node.type === "TSSatisfiesExpression" ||
    node.type === "TSNonNullExpression"
  )
    return staticShape(node.expression);
  switch (node.type) {
    case "Literal":
      return `literal:${typeof node.value}`;
    case "TemplateLiteral":
      return "template";
    case "UnaryExpression":
      return `unary:${node.operator}:${staticShape(node.argument)}`;
    case "ArrayExpression":
      return `array(${node.elements.map((item) => (item === null || item.type === "SpreadElement" ? "invalid" : staticShape(item))).join(",")})`;
    case "ObjectExpression":
      return `object(${node.properties
        .map((property) => {
          if (property.type !== "Property" || property.computed)
            return "invalid";
          if (
            property.key.type !== "Identifier" &&
            property.key.type !== "Literal"
          )
            return "invalid";
          const key =
            property.key.type === "Identifier"
              ? property.key.name
              : String(property.key.value);
          return `${key}:${staticShape(property.value)}`;
        })
        .join(",")})`;
    default:
      return "dynamic";
  }
}

function assertionShape(
  statement: ESTree.Statement,
  context: Context,
  callback: FunctionNode,
): AssertionShape | null {
  if (
    statement.type !== "ExpressionStatement" ||
    statement.expression.type !== "CallExpression"
  )
    return null;
  const matcherCall = statement.expression;
  if (
    matcherCall.callee.type !== "MemberExpression" ||
    matcherCall.callee.computed ||
    matcherCall.callee.property.type !== "Identifier" ||
    matcherCall.arguments.length !== 1
  )
    return null;
  const matcher = matcherCall.callee.property.name;
  if (SNAPSHOT_MATCHERS.test(matcher)) return null;
  const chain = expectCallFromMatcher(matcherCall.callee);
  if (
    chain === null ||
    chain.call.callee.type !== "Identifier" ||
    importedName(chain.call.callee, context, ASSERTION_MODULES) !== "expect" ||
    chain.call.arguments.length !== 1
  )
    return null;
  const observed = chain.call.arguments[0];
  const expected = matcherCall.arguments[0];
  if (
    observed?.type !== "CallExpression" ||
    observed.callee.type !== "Identifier" ||
    observed.arguments.length === 0 ||
    observed.arguments.some(
      (arg) => arg.type === "SpreadElement" || !isStatic(arg),
    ) ||
    expected?.type === "SpreadElement" ||
    expected === undefined ||
    !isStatic(expected)
  )
    return null;
  const skeleton = `${observed.callee.name}/${observed.arguments.map((item) => staticShape(item)).join(",")}/${chain.modifiers.join(".")}/${matcher}/${staticShape(expected)}`;
  const binding = findVariable(
    context.sourceCode.getScope(observed.callee),
    observed.callee.name,
  );
  if (
    binding?.defs.some(
      (definition) =>
        definition.node.range[0] >= callback.range[0] &&
        definition.node.range[1] <= callback.range[1],
    )
  )
    return null;
  const values = [...observed.arguments, expected]
    .map((item) => context.sourceCode.getText(item))
    .join("\u0000");
  return { statement, skeleton, values };
}

function expectCallFromMatcher(
  node: ESTree.MemberExpression,
): { call: ESTree.CallExpression; modifiers: string[] } | null {
  const modifiers: string[] = [];
  let receiver: ESTree.Expression = node.object;
  while (receiver.type === "MemberExpression") {
    const modifier = staticMemberName(receiver);
    if (modifier === null || !EXPECT_MODIFIERS.has(modifier)) return null;
    modifiers.unshift(modifier);
    receiver = receiver.object;
  }
  return receiver.type === "CallExpression"
    ? { call: receiver, modifiers }
    : null;
}

export default createRule<Options, MessageIds>({
  name: "repeated-static-call-cases",
  documentation: REPEATED_STATIC_CALL_CASES_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: REPEATED_STATIC_CALL_CASES_DOCUMENTATION.summary },
    schema: [],
    messages: {
      repeatedStaticCallCases:
        "These {{count}} consecutive assertions repeat a call with static inputs. If independent, use named parameterized cases or subtests; preserve ordered scenarios as one test.",
    },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    if (
      !isTestFile(sourceOrigin(context).filename) ||
      isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)
    )
      return {};
    const duplicateGroups = new Map<ESTree.Node, Map<string, FunctionNode[]>>();
    const pending: PendingFinding[] = [];
    return {
      "CallExpression > ArrowFunctionExpression, CallExpression > FunctionExpression"(
        node: FunctionNode,
      ): void {
        const call = node.parent;
        if (call?.type === "CallExpression") {
          const duplicate = duplicateTestBodyCandidate(call, sourceCode);
          if (duplicate !== null && duplicate.body === node) {
            const groups =
              duplicateGroups.get(duplicate.container) ??
              new Map<string, FunctionNode[]>();
            const owners = groups.get(duplicate.fingerprint) ?? [];
            owners.push(node);
            groups.set(duplicate.fingerprint, owners);
            duplicateGroups.set(duplicate.container, groups);
          }
        }
        const body = node.body;
        if (
          !isDirectTestCallback(node, context) ||
          body?.type !== "BlockStatement"
        )
          return;
        let run: AssertionShape[] = [];
        const flush = (): void => {
          if (
            run.length >= MIN_CASES &&
            new Set(run.map((item) => item.values)).size > 1
          ) {
            const first = run[0];
            const last = run.at(-1);
            const hasComment =
              first !== undefined &&
              last !== undefined &&
              sourceCode
                .getAllComments()
                .some(
                  (comment) =>
                    comment.range[0] >= first.statement.range[0] &&
                    comment.range[1] <= last.statement.range[1],
                );
            if (first !== undefined && last !== undefined && !hasComment) {
              pending.push({
                callback: node,
                count: run.length,
                statement: first.statement,
              });
            }
          }
          run = [];
        };
        for (const statement of body.body) {
          const shape = assertionShape(statement, context, node);
          if (
            shape === null ||
            (run.length > 0 && run[0]?.skeleton !== shape.skeleton)
          )
            flush();
          if (shape !== null) run.push(shape);
        }
        flush();
      },
      "Program:exit"(): void {
        const duplicateOwners = new Set<FunctionNode>();
        for (const groups of duplicateGroups.values()) {
          for (const owners of groups.values()) {
            if (owners.length > 1)
              owners.forEach((owner) => duplicateOwners.add(owner));
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
