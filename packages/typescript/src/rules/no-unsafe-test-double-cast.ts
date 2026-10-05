/**
 * @fileoverview no-unsafe-test-double-cast — prevent mock-backed partial objects from escaping through double assertions.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-unsafe-test-double-cast.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, SourceCode } from "@oxlint/plugins";


import { createRule, type RuleDocumentation } from "./_docs.js";
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

function isUnknown(node: ESTree.TSType): boolean {
  return node.type === "TSUnknownKeyword";
}

function containsMockFactory(node: ESTree.Node, source: SourceCode): boolean {
  if (isMockFactory(node, source)) return true;
  if (node.type === "ObjectExpression") {
    return node.properties.some((property) =>
      property.type === "Property"
        ? containsMockFactory(property.value, source)
        : containsMockFactory(property.argument, source));
  }
  if (node.type === "ArrayExpression") {
    return node.elements.some((element) => element !== null && containsMockFactory(element, source));
  }
  if (node.type === "TSAsExpression" || node.type === "TSTypeAssertion") {
    return containsMockFactory(node.expression, source);
  }
  return false;
}

function isMockFactory(node: ESTree.Node, source: SourceCode): boolean {
  return node.type === "CallExpression" &&
    node.callee.type === "MemberExpression" &&
    !node.callee.computed &&
    node.callee.object.type === "Identifier" &&
    (importedTestMockNamespace(source, node.callee.object) !== null || isUnshadowedTestMockGlobal(source, node.callee.object)) &&
    node.callee.property.type === "Identifier" &&
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
    if (!isTestFile(sourceOrigin(context).filename) || isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) return {};
    return {
      TSAsExpression(node: ESTree.TSAsExpression): void {
        if ((node.expression.type === "TSAsExpression" || node.expression.type === "TSTypeAssertion") && isUnknown(node.expression.typeAnnotation) && containsMockFactory(node.expression.expression, context.sourceCode)) context.report({ node, messageId: "noUnsafeTestDoubleCast" });
      },
      TSTypeAssertion(node: ESTree.TSTypeAssertion): void {
        if ((node.expression.type === "TSAsExpression" || node.expression.type === "TSTypeAssertion") && isUnknown(node.expression.typeAnnotation) && containsMockFactory(node.expression.expression, context.sourceCode)) context.report({ node, messageId: "noUnsafeTestDoubleCast" });
      },
    };
  },
});
