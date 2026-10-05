/**
 * @fileoverview no-unsafe-mock-casting — use framework type helpers for already mocked values, not broad mock casts.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-unsafe-mock-casting.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Variable } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "unsafeMockCast";

const MOCK_TYPE_NAMES: ReadonlySet<string> = new Set([
  "Mock",
  "Mocked",
  "MockedClass",
  "MockedFunction",
  "MockedObject",
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

export const NO_UNSAFE_MOCK_CASTING_DOCUMENTATION = {
  summary: "Disallow casting to mock types like `jest.Mock` or `vi.Mock`. Use `vi.mocked()` or `jest.mocked()` instead.",
  rationale: "A type assertion can claim an unmocked value is a mock and bypass checking between the original callable and the mock API.",
  remediation: "Create the mock or spy first, then use the framework's mocked helper to preserve the original value's type. The helper does not create or verify a runtime mock.",
  category: "testing",
  limitations: ["Only mock types imported from Vitest or Jest modules are inspected. mocked is a type helper, not runtime validation or a replacement for mock setup."],
  references: ["https://vitest.dev/api/vi.html#vi-mocked"],
  examples: [
    {
      id: "typed-mock-helper",
      title: "Use the framework helper",
      outcome: "no-match",
      files: [{ path: "src/client.test.ts", source: "import { vi } from 'vitest'; const client = { read: () => 'value' }; vi.spyOn(client, 'read'); const m = vi.mocked(client.read);" }],
      focusPath: "src/client.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "mock-type-assertion",
      title: "Do not assert that a value is a mock",
      outcome: "match",
      files: [{ path: "src/client.test.ts", source: "import type * as vi from \"vitest\"; const m = myFn as vi.Mock;" }],
      focusPath: "src/client.test.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<[], MessageIds>({
  name: "no-unsafe-mock-casting",
  documentation: NO_UNSAFE_MOCK_CASTING_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow casting to mock types like `jest.Mock` or `vi.Mock`. Use `vi.mocked()` or `jest.mocked()` instead.",
    },
    schema: [],
    messages: {
      unsafeMockCast:
        "Avoid a broad Mock cast. After creating the mock or spy, use `vi.mocked(fn)` or `jest.mocked(fn)` to retain its original type; the helper does not create a runtime mock.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) {
      return {};
    }

    const directBindings = new Set<Variable>();
    const namespaceBindings = new Set<Variable>();

    function resolve(identifier: ESTree.BindingIdentifier): Variable | null {
      return findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
    }

    function record(
      identifier: ESTree.BindingIdentifier,
      destination: Set<Variable>,
    ): void {
      const binding = resolve(identifier);
      if (binding !== null) destination.add(binding);
    }

    function checkAssertion(
      node: ESTree.TSAsExpression | ESTree.TSTypeAssertion,
    ): void {
      if (isMockTypeReference(node.typeAnnotation)) {
        context.report({ node, messageId: "unsafeMockCast" });
      }
    }

    function isMockTypeReference(node: ESTree.TSType): boolean {
      if (node.type !== "TSTypeReference") return false;
      const typeName = node.typeName;
      if (typeName.type === "Identifier") {
        const binding = resolve(typeName);
        return binding !== null && directBindings.has(binding);
      }
      if (
        typeName.type === "TSQualifiedName" &&
        typeName.left.type === "Identifier" &&
        MOCK_TYPE_NAMES.has(typeName.right.name)
      ) {
        const binding = resolve(typeName.left);
        return binding !== null && namespaceBindings.has(binding);
      }
      return false;
    }

    return {
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (!MOCK_MODULES.has(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (specifier.type === "ImportNamespaceSpecifier") {
            record(specifier.local, namespaceBindings);
          } else if (
            specifier.type === "ImportSpecifier" &&
            MOCK_TYPE_NAMES.has(
              specifier.imported.type === "Identifier"
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
