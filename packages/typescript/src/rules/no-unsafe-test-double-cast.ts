/**
 * @fileoverview no-unsafe-test-double-cast — prevent mock-backed partial objects from escaping through double assertions.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-unsafe-test-double-cast.test.ts
 */

import { ASTUtils, AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { unwrapExpression } from "./_unwrap-expression.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { importedTestMockNamespace, isUnshadowedTestMockGlobal } from "./_test-mock-provenance.js";

type MessageIds = "noUnsafeTestDoubleCast";

export const NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION = {
  summary: "Disallow mock-backed test doubles that bypass collaborator contracts through double assertions.",
  rationale: "Casting a partial object through unknown hides missing or stale collaborator members, so production interface changes can compile while the test double silently drifts.",
  remediation: "Define the smallest injected port and implement a typed recording fake, or make the fixture satisfy the real contract without passing through unknown.",
  category: "testing",
  limitations: ["Only generated-free test files and direct double assertions containing a fn or spyOn call from a resolved Vitest/Jest import or an unshadowed vi/jest global are checked. Import aliases and mixed assertion syntax are supported; local shadowing, type-only imports, indirect value aliases, arbitrary payload casts and dynamic API replacement are not inferred."],
  examples: [
    { id: "typed-recording-fake", title: "Use a typed recording fake", outcome: "no-match", files: [{ path: "service.test.ts", source: "const client = { read: async () => ({ id: '1' }) } satisfies Pick<Client, 'read'>;" }], focusPath: "service.test.ts", expectedCount: 0, public: true },
    { id: "mock-backed-double-cast", title: "Do not hide a partial mock behind unknown", outcome: "match", files: [{ path: "service.test.ts", source: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;" }], focusPath: "service.test.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function isUnknown(node: TSESTree.TypeNode): boolean {
  return node.type === AST_NODE_TYPES.TSUnknownKeyword;
}

function containsMockFactory(node: TSESTree.Node, source: TSESLint.SourceCode): boolean {
  node = unwrapExpression(node);
  if (isMockFactory(node, source)) return true;
  if (node.type === AST_NODE_TYPES.ObjectExpression) {
    return node.properties.some((property) =>
      property.type === AST_NODE_TYPES.Property
        ? containsMockFactory(property.value, source)
        : containsMockFactory(property.argument, source));
  }
  if (node.type === AST_NODE_TYPES.ArrayExpression) {
    return node.elements.some((element) => element !== null && containsMockFactory(element, source));
  }
  return false;
}

function isMockFactory(node: TSESTree.Node, source: TSESLint.SourceCode): boolean {
  const unwrappedNodeCallee = node.type === "CallExpression" || node.type === "NewExpression" ? unwrapExpression(node.callee) : null;
  if (node.type !== AST_NODE_TYPES.CallExpression || unwrappedNodeCallee?.type !== AST_NODE_TYPES.MemberExpression) return false;
  const receiver = unwrapExpression(unwrappedNodeCallee.object);
  return node.type === AST_NODE_TYPES.CallExpression &&
    unwrappedNodeCallee?.type === AST_NODE_TYPES.MemberExpression &&
    receiver.type === AST_NODE_TYPES.Identifier &&
    (importedTestMockNamespace(source, receiver) !== null || isUnshadowedTestMockGlobal(source, receiver)) &&
    ASTUtils.getPropertyName(unwrappedNodeCallee) !== null &&
    ["fn", "spyOn"].includes((ASTUtils.getPropertyName(unwrappedNodeCallee) ?? ""));
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
        if ((node.expression.type === AST_NODE_TYPES.TSAsExpression || node.expression.type === AST_NODE_TYPES.TSTypeAssertion) && isUnknown(node.expression.typeAnnotation) && containsMockFactory(node.expression.expression, context.sourceCode)) context.report({ node, messageId: "noUnsafeTestDoubleCast" });
      },
      TSTypeAssertion(node: TSESTree.TSTypeAssertion): void {
        if ((node.expression.type === AST_NODE_TYPES.TSAsExpression || node.expression.type === AST_NODE_TYPES.TSTypeAssertion) && isUnknown(node.expression.typeAnnotation) && containsMockFactory(node.expression.expression, context.sourceCode)) context.report({ node, messageId: "noUnsafeTestDoubleCast" });
      },
    };
  },
});
