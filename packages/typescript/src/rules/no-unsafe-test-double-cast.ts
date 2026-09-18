/**
 * @fileoverview no-unsafe-test-double-cast — prevent mock-backed partial objects from escaping through double assertions.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-unsafe-test-double-cast.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "noUnsafeTestDoubleCast";

export const NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION = {
  summary: "Disallow mock-backed test doubles that bypass collaborator contracts through double assertions.",
  rationale: "Casting a partial object through unknown or any hides missing or stale collaborator members, so production interface changes can compile while the test double silently drifts.",
  remediation: "Define the smallest injected port and implement a typed recording fake, or make the fixture satisfy the real contract without passing through unknown.",
  category: "testing",
  limitations: ["Only generated-free test files and double assertions backed by a Vitest or Jest mock factory are checked. Local immutable aliases are followed; mutable aliases, helper return values, and arbitrary payload casts are excluded."],
  examples: [
    { id: "typed-recording-fake", title: "Use a typed recording fake", outcome: "no-match", files: [{ path: "service.test.ts", source: "const client = { read: async () => ({ id: '1' }) } satisfies Pick<Client, 'read'>;" }], focusPath: "service.test.ts", expectedCount: 0, public: true },
    { id: "mock-backed-double-cast", title: "Do not hide a partial mock behind unknown", outcome: "match", files: [{ path: "service.test.ts", source: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;" }], focusPath: "service.test.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function isBridgeType(node: TSESTree.TypeNode): boolean {
  return node.type === AST_NODE_TYPES.TSUnknownKeyword || node.type === AST_NODE_TYPES.TSAnyKeyword;
}

function isAssertion(node: TSESTree.Node): node is TSESTree.TSAsExpression | TSESTree.TSTypeAssertion {
  return node.type === AST_NODE_TYPES.TSAsExpression || node.type === AST_NODE_TYPES.TSTypeAssertion;
}

function isFrameworkImport(source: string, imported: string): boolean {
  return (source === "vitest" && imported === "vi") || (source === "@jest/globals" && imported === "jest");
}

export default createRule<[], MessageIds>({
  name: "no-unsafe-test-double-cast",
  documentation: NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION.summary },
    schema: [],
    messages: { noUnsafeTestDoubleCast: "This mock-backed partial object bypasses the collaborator contract through an unsafe bridge type. Use a narrow injected port and typed recording fake, or make the fixture satisfy the real contract." },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    const namespaces = new Set<TSESLint.Scope.Variable>();
    const resolve = (identifier: TSESTree.Identifier): TSESLint.Scope.Variable | null => ASTUtils.findVariable(context.sourceCode.getScope(identifier), identifier.name);

    function isFrameworkNamespace(identifier: TSESTree.Identifier): boolean {
      const binding = resolve(identifier);
      if (binding === null || binding.defs.length === 0) return identifier.name === "vi" || identifier.name === "jest";
      return namespaces.has(binding);
    }

    function isMockFactory(node: TSESTree.Node): boolean {
      if (node.type !== AST_NODE_TYPES.CallExpression || node.callee.type !== AST_NODE_TYPES.MemberExpression || node.callee.computed) return false;
      const receiver = node.callee.object;
      if (receiver.type === AST_NODE_TYPES.CallExpression && isMockFactory(receiver)) return true;
      return receiver.type === AST_NODE_TYPES.Identifier &&
        node.callee.property.type === AST_NODE_TYPES.Identifier &&
        (node.callee.property.name === "fn" || node.callee.property.name === "spyOn") &&
        isFrameworkNamespace(receiver);
    }

    function immutableInitializer(identifier: TSESTree.Identifier): { binding: TSESLint.Scope.Variable; init: TSESTree.Expression } | null {
      const binding = resolve(identifier);
      const definition = binding?.defs.length === 1 ? binding.defs[0] : undefined;
      if (binding === null || definition?.type !== "Variable" || definition.parent.kind !== "const" || definition.node.init === null || binding.references.some((reference) => reference.isWrite() && reference.init !== true)) return null;
      return { binding, init: definition.node.init };
    }

    function containsMockFactory(node: TSESTree.Node, seen: Set<TSESLint.Scope.Variable>): boolean {
      if (isMockFactory(node)) return true;
      if (node.type === AST_NODE_TYPES.Identifier) {
        const resolved = immutableInitializer(node);
        if (resolved === null || seen.has(resolved.binding)) return false;
        seen.add(resolved.binding);
        return containsMockFactory(resolved.init, seen);
      }
      if (node.type === AST_NODE_TYPES.ObjectExpression) {
        return node.properties.some((property) =>
          property.type === AST_NODE_TYPES.Property
            ? containsMockFactory(property.value, new Set(seen))
            : containsMockFactory(property.argument, new Set(seen)));
      }
      if (node.type === AST_NODE_TYPES.ArrayExpression) {
        return node.elements.some((element) => element !== null && containsMockFactory(element, new Set(seen)));
      }
      if (isAssertion(node)) return containsMockFactory(node.expression, seen);
      return false;
    }

    function reportUnsafeAssertion(node: TSESTree.TSAsExpression | TSESTree.TSTypeAssertion): void {
      if (isAssertion(node.parent) && node.parent.expression === node) return;
      const bridge = node.expression;
      if (isAssertion(bridge) && isBridgeType(bridge.typeAnnotation) && containsMockFactory(bridge.expression, new Set())) context.report({ node, messageId: "noUnsafeTestDoubleCast" });
    }

    return {
      Program(node: TSESTree.Program): void {
        for (const statement of node.body) {
          if (statement.type !== AST_NODE_TYPES.ImportDeclaration || typeof statement.source.value !== "string") continue;
          for (const specifier of statement.specifiers) {
            if (specifier.type !== AST_NODE_TYPES.ImportSpecifier) continue;
            const imported = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : specifier.imported.value;
            if (!isFrameworkImport(statement.source.value, imported)) continue;
            const binding = resolve(specifier.local);
            if (binding !== null) namespaces.add(binding);
          }
        }
      },
      TSAsExpression(node: TSESTree.TSAsExpression): void {
        reportUnsafeAssertion(node);
      },
      TSTypeAssertion(node: TSESTree.TSTypeAssertion): void {
        reportUnsafeAssertion(node);
      },
    };
  },
});
