/**
 * @fileoverview no-unsafe-mock-casting — use framework type helpers for already mocked values, not broad mock casts.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-unsafe-mock-casting.test.ts
 */

import {
  type TSESLint,
  type TSESTree,
  AST_NODE_TYPES,
} from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { retainsNamedTypeUses, typeBinding } from "./_type-binding.js";
import { isUnusedPrivateBinding } from "./_unused-private-binding.js";

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
  autofix: "safe",
  limitations: ["Only mock types imported from Vitest or Jest modules are inspected. mocked is a type helper, not runtime validation or a replacement for mock setup.",
    "Automatic fixes remove only an erased mock assertion from an unused private unannotated const initialized by an identifier, optionally through unknown assertions. Every erased named type/generic/namespace binding must retain an independent exported type use; potentially erased annotations and self references cannot witness each other. Evaluation is unchanged; referenced/exported bindings, contextual expressions, scripts, declaration files, eval and comments remain manual."],
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
    {
      id: "safe-autofix",
      title: "Retain an unused private value's actual inferred type",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "import type { Mock } from 'vitest'; export type RetainedMock = Mock; declare const value: unknown; const fake = value as Mock;" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "import type { Mock } from 'vitest'; export type RetainedMock = Mock; declare const value: unknown; const fake = value;" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<[], MessageIds>({
  name: "no-unsafe-mock-casting",
  documentation: NO_UNSAFE_MOCK_CASTING_DOCUMENTATION,
  meta: {
    type: "problem",
    fixable: "code",
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
    if (isGeneratedFile(context, context.sourceCode.text)) {
      return {};
    }

    const directBindings = new Set<TSESLint.Scope.Variable>();
    const namespaceBindings = new Set<TSESLint.Scope.Variable>();

    function resolve(identifier: TSESTree.Identifier): TSESLint.Scope.Variable | null {
      return typeBinding(context.sourceCode, identifier);
    }

    function record(
      identifier: TSESTree.Identifier,
      destination: Set<TSESLint.Scope.Variable>,
    ): void {
      const binding = resolve(identifier);
      if (binding !== null) destination.add(binding);
    }

    function checkAssertion(
      node: TSESTree.TSAsExpression | TSESTree.TSTypeAssertion,
    ): void {
      if (isMockTypeReference(node.typeAnnotation)) {
        context.report({ node, messageId: "unsafeMockCast", fix: privateIdentifierAssertionFix(context.sourceCode, node, context.filename) });
      }
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

function privateIdentifierAssertionFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.TSAsExpression | TSESTree.TSTypeAssertion,
  filename: string,
): TSESLint.ReportFixFunction | null {
  const declaration = node.parent;
  if (declaration.type !== AST_NODE_TYPES.VariableDeclarator || declaration.init !== node ||
    declaration.id.type !== AST_NODE_TYPES.Identifier || declaration.id.typeAnnotation !== undefined ||
    declaration.parent.kind !== "const" || !isUnusedPrivateBinding(sourceCode, declaration, declaration.id, filename) ||
    sourceCode.getCommentsInside(node).length > 0 || !retainsNamedTypeUses(sourceCode, node.typeAnnotation)) return null;
  let value = node.expression;
  while ((value.type === AST_NODE_TYPES.TSAsExpression || value.type === AST_NODE_TYPES.TSTypeAssertion) &&
    value.typeAnnotation.type === AST_NODE_TYPES.TSUnknownKeyword) value = value.expression;
  if (value.type !== AST_NODE_TYPES.Identifier) return null;
  const replacement = sourceCode.getText(value) + sourceCode.getText(node).replace(/[^\r\n]/gu, "");
  return (fixer) => fixer.replaceText(node, replacement);
}
