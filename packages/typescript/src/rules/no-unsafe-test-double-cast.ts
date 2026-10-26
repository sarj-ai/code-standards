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
import { isUnusedPrivateBinding } from "./_unused-private-binding.js";
import { retainsNamedTypeUses } from "./_type-binding.js";

type MessageIds = "noUnsafeTestDoubleCast";

export const NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION = {
  summary: "Disallow mock-backed test doubles that bypass collaborator contracts through double assertions.",
  rationale: "Casting a partial object through unknown hides missing or stale collaborator members, so production interface changes can compile while the test double silently drifts.",
  remediation: "Define the smallest injected port and implement a typed recording fake, or make the fixture satisfy the real contract without passing through unknown.",
  category: "testing",
  autofix: "safe",
  limitations: ["Only generated-free test files and direct double assertions containing a fn or spyOn call from a resolved Vitest/Jest import or an unshadowed vi/jest global are checked. Import aliases and mixed assertion syntax are supported; local shadowing, type-only imports, indirect value aliases, arbitrary payload casts and dynamic API replacement are not inferred.",
    "Automatic fixes remove only erased double assertions on an unused private unannotated const initialized by a plain object containing primitive literals, nested plain objects and zero-argument canonical mock fn calls. Every erased named/generic/namespace binding must retain an independent exported type use outside self references and other erasable annotations. They retain the original runtime expression; exports, reads, contextual functions, generic mock factories, spreads, accessors, comments, scripts, declaration files and eval remain manual."],
  examples: [
    { id: "typed-recording-fake", title: "Use a typed recording fake", outcome: "no-match", files: [{ path: "service.test.ts", source: "const client = { read: async () => ({ id: '1' }) } satisfies Pick<Client, 'read'>;" }], focusPath: "service.test.ts", expectedCount: 0, public: true },
    { id: "mock-backed-double-cast", title: "Do not hide a partial mock behind unknown", outcome: "match", files: [{ path: "service.test.ts", source: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;" }], focusPath: "service.test.ts", expectedCount: 1, public: true },
    { id: "safe-autofix", title: "Retain an unused private mock object's actual inferred shape", outcome: "match", files: [{ path: "service.test.ts", source: "import { vi } from 'vitest'; interface Client { read(): string } export type RetainedClient = Client; const client = { read: vi.fn() } as unknown as Client;" }], fixedFiles: [{ path: "service.test.ts", source: "import { vi } from 'vitest'; interface Client { read(): string } export type RetainedClient = Client; const client = { read: vi.fn() };" }], focusPath: "service.test.ts", expectedCount: 1 },
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
    fixable: "code",
    docs: { description: NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION.summary },
    schema: [],
    messages: { noUnsafeTestDoubleCast: "This mock-backed partial object bypasses the collaborator contract through `unknown`. Use a narrow injected port and typed recording fake, or make the fixture satisfy the real contract." },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context) || isGeneratedFile(context, context.sourceCode.text)) return {};
    return {
      TSAsExpression(node: TSESTree.TSAsExpression): void {
        if ((node.expression.type === AST_NODE_TYPES.TSAsExpression || node.expression.type === AST_NODE_TYPES.TSTypeAssertion) && isUnknown(node.expression.typeAnnotation) && containsMockFactory(node.expression.expression, context.sourceCode)) context.report({ node, messageId: "noUnsafeTestDoubleCast", fix: privateMockObjectFix(context.sourceCode, node, context.filename) });
      },
      TSTypeAssertion(node: TSESTree.TSTypeAssertion): void {
        if ((node.expression.type === AST_NODE_TYPES.TSAsExpression || node.expression.type === AST_NODE_TYPES.TSTypeAssertion) && isUnknown(node.expression.typeAnnotation) && containsMockFactory(node.expression.expression, context.sourceCode)) context.report({ node, messageId: "noUnsafeTestDoubleCast", fix: privateMockObjectFix(context.sourceCode, node, context.filename) });
      },
    };
  },
});

function privateMockObjectFix(
  sourceCode: TSESLint.SourceCode,
  node: TSESTree.TSAsExpression | TSESTree.TSTypeAssertion,
  filename: string,
): TSESLint.ReportFixFunction | null {
  const declaration = node.parent;
  const inner = node.expression;
  if ((inner.type !== AST_NODE_TYPES.TSAsExpression && inner.type !== AST_NODE_TYPES.TSTypeAssertion) ||
    declaration.type !== AST_NODE_TYPES.VariableDeclarator || declaration.init !== node ||
    declaration.id.type !== AST_NODE_TYPES.Identifier || declaration.id.typeAnnotation !== undefined ||
    declaration.parent.kind !== "const" || !isUnusedPrivateBinding(sourceCode, declaration, declaration.id, filename) ||
    sourceCode.getCommentsInside(node).length > 0 || !simpleMockObject(inner.expression, sourceCode) ||
    !retainsNamedTypeUses(sourceCode, node.typeAnnotation)) return null;
  const expression = sourceCode.getText(inner.expression);
  const expressionNewlines = expression.replace(/[^\r\n]/gu, "");
  const removedNewlines = sourceCode.getText(node).replace(/[^\r\n]/gu, "").slice(expressionNewlines.length);
  const replacement = expression + removedNewlines;
  return (fixer) => fixer.replaceText(node, replacement);
}

function simpleMockObject(node: TSESTree.Node, sourceCode: TSESLint.SourceCode): boolean {
  if (node.type !== AST_NODE_TYPES.ObjectExpression) return false;
  return node.properties.every((property) => {
    if (property.type !== AST_NODE_TYPES.Property || property.computed || property.method || property.kind !== "init") return false;
    const value = property.value;
    if (value.type === AST_NODE_TYPES.Literal) return value.value === null ||
      ["string", "number", "boolean", "bigint"].includes(typeof value.value);
    if (value.type === AST_NODE_TYPES.ObjectExpression) return simpleMockObject(value, sourceCode);
    return value.type === AST_NODE_TYPES.CallExpression && !value.optional && value.arguments.length === 0 &&
      value.typeArguments === undefined && value.callee.type === AST_NODE_TYPES.MemberExpression && !value.callee.optional &&
      ASTUtils.getPropertyName(value.callee) === "fn" && isMockFactory(value, sourceCode);
  });
}
