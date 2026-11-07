/**
 * @fileoverview no-unsafe-mock-casting — use framework type helpers for already mocked values, not broad mock casts.
 *
 * Port of the 18.x `no-unsafe-mock-casting` rule. Same algorithm; the
 * generated-file gate and per-file binding reset run in `before()`. Oxlint
 * sets a missing `typeAnnotation` to `null` (TS-ESTree: `undefined`), so the
 * fix accepts both.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-unsafe-mock-casting.test.ts
 */

import type { FixFn } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile } from "../utils/paths.js";
import { retainsNamedTypeUses, typeBinding } from "../utils/type-binding.js";
import { isUnusedPrivateBinding } from "../utils/unused-private-binding.js";

const NAME = "no-unsafe-mock-casting";
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

type Assertion = ESTree.TSAsExpression | ESTree.TSTypeAssertion;
type Identifier = Node & { type: "Identifier"; name: string };

function privateIdentifierAssertionFix(sourceCode: SourceCode, node: Assertion, filename: string): FixFn | null {
  const declaration = parentOf(node);
  if (declaration?.type !== "VariableDeclarator" || declaration.init !== node ||
    declaration.id.type !== "Identifier" || declaration.id.typeAnnotation != null ||
    (parentOf(declaration) as ESTree.VariableDeclaration | null)?.kind !== "const" ||
    !isUnusedPrivateBinding(sourceCode, declaration, declaration.id, filename) ||
    sourceCode.getCommentsInside(node).length > 0 || !retainsNamedTypeUses(sourceCode, node.typeAnnotation)) return null;
  let value: Node = node.expression;
  while ((value.type === "TSAsExpression" || value.type === "TSTypeAssertion") &&
    value.typeAnnotation.type === "TSUnknownKeyword") value = value.expression;
  if (value.type !== "Identifier") return null;
  const replacement = sourceCode.getText(value) + sourceCode.getText(node).replace(/[^\r\n]/gu, "");
  return (fixer) => fixer.replaceText(node, replacement);
}

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description:
        "Disallow casting to mock types like `jest.Mock` or `vi.Mock`. Use `vi.mocked()` or `jest.mocked()` instead.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      unsafeMockCast:
        "Avoid a broad Mock cast. After creating the mock or spy, use `vi.mocked(fn)` or `jest.mocked(fn)` to retain its original type; the helper does not create a runtime mock.",
    },
  },
  createOnce(context) {
    const directBindings = new Set<TsVariable>();
    const namespaceBindings = new Set<TsVariable>();

    function resolve(identifier: Identifier): TsVariable | null {
      return typeBinding(context.sourceCode, identifier);
    }

    function record(identifier: Identifier, destination: Set<TsVariable>): void {
      const binding = resolve(identifier);
      if (binding !== null) destination.add(binding);
    }

    function checkAssertion(node: Assertion): void {
      // A mock type only resolves through a recorded import binding.
      if (directBindings.size === 0 && namespaceBindings.size === 0) return;
      if (isMockTypeReference(node.typeAnnotation)) {
        const fix = privateIdentifierAssertionFix(context.sourceCode, node, context.filename);
        context.report({ node, messageId: "unsafeMockCast", ...(fix !== null && { fix }) });
      }
    }

    function isMockTypeReference(node: ESTree.TSType): boolean {
      if (node.type !== "TSTypeReference") return false;
      const typeName = node.typeName;
      if (typeName.type === "Identifier") {
        const binding = resolve(typeName);
        return binding !== null && directBindings.has(binding);
      }
      if (typeName.type === "TSQualifiedName" && typeName.left.type === "Identifier" && MOCK_TYPE_NAMES.has(typeName.right.name)) {
        const binding = resolve(typeName.left);
        return binding !== null && namespaceBindings.has(binding);
      }
      return false;
    }

    return {
      before() {
        directBindings.clear();
        namespaceBindings.clear();
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      ImportDeclaration(node) {
        if (!MOCK_MODULES.has(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (specifier.type === "ImportNamespaceSpecifier") {
            record(specifier.local, namespaceBindings);
          } else if (
            specifier.type === "ImportSpecifier" &&
            MOCK_TYPE_NAMES.has(importSpecifierName(specifier))
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
