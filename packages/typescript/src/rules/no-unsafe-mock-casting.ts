/**
 * @fileoverview no-unsafe-mock-casting — a cast to `vi.Mock` / `jest.Mock` asserts a mock that may not exist; `vi.mocked()` checks it.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-unsafe-mock-casting.test.ts
 */

import {
  type TSESLint,
  type TSESTree,
  AST_NODE_TYPES,
  ASTUtils,
} from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "unsafeMockCast";

const MOCK_TYPE_NAMES: ReadonlySet<string> = new Set([
  "Mock",
  "MockInstance",
  "SpyInstance",
]);
const MOCK_MODULES: ReadonlySet<string> = new Set([
  "vitest",
  "@vitest/spy",
  "jest",
  "jest-mock",
  "@jest/globals",
]);

export default createRule<[], MessageIds>({
  name: "no-unsafe-mock-casting",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow casting to mock types like `jest.Mock` or `vi.Mock`. Use `vi.mocked()` or `jest.mocked()` instead.",
    },
    schema: [],
    messages: {
      unsafeMockCast:
        "Do not cast to a Mock type. Use `vi.mocked(fn)` or `jest.mocked(fn)` instead to preserve type safety.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

    const directBindings = new Set<TSESLint.Scope.Variable>();
    const namespaceBindings = new Set<TSESLint.Scope.Variable>();

    function resolve(identifier: TSESTree.Identifier): TSESLint.Scope.Variable | null {
      return ASTUtils.findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
    }

    function record(
      identifier: TSESTree.Identifier,
      destination: Set<TSESLint.Scope.Variable>,
    ): void {
      const binding = resolve(identifier);
      if (binding !== null) destination.add(binding);
    }

    function isMockTypeReference(node: TSESTree.TypeNode): boolean {
      if (node.type !== AST_NODE_TYPES.TSTypeReference) return false;
      const typeName = node.typeName;
      if (typeName.type === AST_NODE_TYPES.Identifier) {
        const binding = resolve(typeName);
        return binding !== null && directBindings.has(binding);
      }
      if (
        typeName.type === AST_NODE_TYPES.TSQualifiedName &&
        typeName.left.type === AST_NODE_TYPES.Identifier &&
        MOCK_TYPE_NAMES.has(typeName.right.name)
      ) {
        const binding = resolve(typeName.left);
        return binding !== null && namespaceBindings.has(binding);
      }
      return false;
    }

    function checkAssertion(
      node: TSESTree.TSAsExpression | TSESTree.TSTypeAssertion,
    ): void {
      if (isMockTypeReference(node.typeAnnotation)) {
        context.report({ node, messageId: "unsafeMockCast" });
      }
    }

    return {
      ImportDeclaration(node: TSESTree.ImportDeclaration): void {
        if (!MOCK_MODULES.has(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier) {
            record(specifier.local, namespaceBindings);
          } else if (
            specifier.type === AST_NODE_TYPES.ImportSpecifier &&
            MOCK_TYPE_NAMES.has(
              specifier.imported.type === AST_NODE_TYPES.Identifier
                ? specifier.imported.name
                : specifier.imported.value,
            )
          ) {
            record(specifier.local, directBindings);
          }
        }
      },
      TSAsExpression: checkAssertion,
      TSTypeAssertion: checkAssertion,
    };
  },
});
