/**
 * @fileoverview no-unsafe-test-double-cast — prevent mock-backed partial objects from escaping through double assertions.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-unsafe-test-double-cast.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "noUnsafeTestDoubleCast";

export const NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION = {
  summary: "Disallow mock-backed test doubles that bypass collaborator contracts through double assertions.",
  rationale: "Casting a partial object through unknown hides missing or stale collaborator members, so production interface changes can compile while the test double silently drifts.",
  remediation: "Define the smallest injected port and implement a typed recording fake, or make the fixture satisfy the real contract without passing through unknown.",
  category: "testing",
  limitations: ["Only generated-free test files and direct double assertions whose value contains a Vitest or Jest mock factory are checked. Indirect aliases and arbitrary payload casts are excluded."],
  examples: [
    { id: "typed-recording-fake", title: "Use a typed recording fake", outcome: "no-match", files: [{ path: "service.test.ts", source: "const client = { read: async () => ({ id: '1' }) } satisfies Pick<Client, 'read'>;" }], focusPath: "service.test.ts", expectedCount: 0, public: true },
    { id: "mock-backed-double-cast", title: "Do not hide a partial mock behind unknown", outcome: "match", files: [{ path: "service.test.ts", source: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;" }], focusPath: "service.test.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function isUnknown(node: TSESTree.TypeNode): boolean {
  return node.type === AST_NODE_TYPES.TSUnknownKeyword;
}

function containsMockFactory(node: TSESTree.Node): boolean {
  if (isMockFactory(node)) return true;
  if (node.type === AST_NODE_TYPES.ObjectExpression) {
    return node.properties.some((property) =>
      property.type === AST_NODE_TYPES.Property
        ? containsMockFactory(property.value)
        : containsMockFactory(property.argument));
  }
  if (node.type === AST_NODE_TYPES.ArrayExpression) {
    return node.elements.some((element) => element !== null && containsMockFactory(element));
  }
  if (node.type === AST_NODE_TYPES.TSAsExpression || node.type === AST_NODE_TYPES.TSTypeAssertion) {
    return containsMockFactory(node.expression);
  }
  return false;
}

function isMockFactory(node: TSESTree.Node): boolean {
  return node.type === AST_NODE_TYPES.CallExpression &&
    node.callee.type === AST_NODE_TYPES.MemberExpression &&
    !node.callee.computed &&
    node.callee.object.type === AST_NODE_TYPES.Identifier &&
    (node.callee.object.name === "vi" || node.callee.object.name === "jest") &&
    node.callee.property.type === AST_NODE_TYPES.Identifier &&
    ["fn", "spyOn"].includes(node.callee.property.name);
}

export default createRule<[], MessageIds>({
  name: "no-unsafe-test-double-cast",
  documentation: NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION.summary },
    schema: [],
    messages: { noUnsafeTestDoubleCast: "This mock-backed partial object bypasses the collaborator contract through `unknown`. Use a narrow injected port and typed recording fake, or make the fixture satisfy the real contract." },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    return {
      TSAsExpression(node: TSESTree.TSAsExpression): void {
        if (node.expression.type === AST_NODE_TYPES.TSAsExpression && isUnknown(node.expression.typeAnnotation) && containsMockFactory(node.expression.expression)) context.report({ node, messageId: "noUnsafeTestDoubleCast" });
      },
      TSTypeAssertion(node: TSESTree.TSTypeAssertion): void {
        if (node.expression.type === AST_NODE_TYPES.TSTypeAssertion && isUnknown(node.expression.typeAnnotation) && containsMockFactory(node.expression.expression)) context.report({ node, messageId: "noUnsafeTestDoubleCast" });
      },
    };
  },
});
