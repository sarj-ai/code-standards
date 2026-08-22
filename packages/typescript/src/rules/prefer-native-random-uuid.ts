/**
 * @fileoverview prefer-native-random-uuid — Node 22's native UUID generator makes the dependency unnecessary for UUID v4 calls.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-native-random-uuid.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "preferNative" | "replaceWithNative";
type Options = readonly [];

export const PREFER_NATIVE_RANDOM_UUID_DOCUMENTATION = {
  summary: "Prefer `globalThis.crypto.randomUUID()` over resolved zero-argument UUID v4 bindings from the `uuid` package.",
  rationale: "The platform implementation avoids an unnecessary dependency for standard random UUID generation.",
  remediation: "Call `globalThis.crypto.randomUUID()` and remove the unused `uuid` v4 import when possible.",
  category: "maintainability",
  autofix: "suggestion",
  limitations: ["Only resolved zero-argument UUID v4 calls are reported; customized and other UUID versions are excluded."],
  examples: [
    { id: "native-random-uuid", title: "Use the platform UUID generator", outcome: "no-match", files: [{ path: "src/id.ts", source: "const id = globalThis.crypto.randomUUID();" }], focusPath: "src/id.ts", expectedCount: 0, public: true },
    { id: "uuid-v4-package", title: "Do not call uuid v4 without options", outcome: "match", files: [{ path: "src/id.ts", source: "import { v4 } from 'uuid'; const id = v4();" }], focusPath: "src/id.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

type ScopeVariable = TSESLint.Scope.Variable;

function requireUuid(node: TSESTree.Node | null): boolean {
  return (
    node?.type === AST_NODE_TYPES.CallExpression &&
    node.callee.type === AST_NODE_TYPES.Identifier &&
    node.callee.name === "require" &&
    node.arguments.length === 1 &&
    node.arguments[0]?.type === AST_NODE_TYPES.Literal &&
    node.arguments[0].value === "uuid"
  );
}

export default createRule<Options, MessageIds>({
  name: "prefer-native-random-uuid",
  documentation: PREFER_NATIVE_RANDOM_UUID_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Prefer `globalThis.crypto.randomUUID()` over resolved zero-argument UUID v4 bindings from the `uuid` package.",
    },
    hasSuggestions: true,
    schema: [],
    messages: {
      preferNative:
        "Use the Node 22 native `globalThis.crypto.randomUUID()` instead of the `uuid` package for UUID v4.",
      replaceWithNative: "Replace this UUID v4 call with the native implementation.",
    },
  },
  defaultOptions: [],
  create(context) {
    const directBindings = new Set<ScopeVariable>();
    const namespaceBindings = new Set<ScopeVariable>();

    function resolve(identifier: TSESTree.Identifier): ScopeVariable | null {
      return ASTUtils.findVariable(context.sourceCode.getScope(identifier), identifier.name);
    }

    function record(identifier: TSESTree.Identifier, destination: Set<ScopeVariable>): void {
      const variable = resolve(identifier);
      if (variable !== null) destination.add(variable);
    }

    function report(node: TSESTree.CallExpression): void {
      context.report({
        node,
        messageId: "preferNative",
        suggest: [
          {
            messageId: "replaceWithNative",
            fix: (fixer) => fixer.replaceText(node, "globalThis.crypto.randomUUID()"),
          },
        ],
      });
    }

    return {
      ImportDeclaration(node: TSESTree.ImportDeclaration): void {
        if (node.source.value !== "uuid") return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === AST_NODE_TYPES.ImportSpecifier &&
            (specifier.imported.type === AST_NODE_TYPES.Identifier
              ? specifier.imported.name === "v4"
              : specifier.imported.value === "v4")
          ) {
            record(specifier.local, directBindings);
          } else if (specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier) {
            record(specifier.local, namespaceBindings);
          }
        }
      },
      VariableDeclarator(node: TSESTree.VariableDeclarator): void {
        if (node.parent.kind !== "const" || !requireUuid(node.init)) return;
        if (
          node.init?.type !== AST_NODE_TYPES.CallExpression ||
          node.init.callee.type !== AST_NODE_TYPES.Identifier ||
          (resolve(node.init.callee)?.defs.length ?? 0) > 0
        ) {
          return;
        }
        if (node.id.type === AST_NODE_TYPES.Identifier) {
          record(node.id, namespaceBindings);
          return;
        }
        if (node.id.type !== AST_NODE_TYPES.ObjectPattern) return;
        for (const property of node.id.properties) {
          if (
            property.type === AST_NODE_TYPES.Property &&
            !property.computed &&
            ((property.key.type === AST_NODE_TYPES.Identifier && property.key.name === "v4") ||
              (property.key.type === AST_NODE_TYPES.Literal && property.key.value === "v4")) &&
            property.value.type === AST_NODE_TYPES.Identifier
          ) {
            record(property.value, directBindings);
          }
        }
      },
      "CallExpression:exit"(node: TSESTree.CallExpression): void {
        if (node.arguments.length !== 0) return;
        if (node.callee.type === AST_NODE_TYPES.Identifier) {
          const variable = resolve(node.callee);
          if (variable !== null && directBindings.has(variable)) report(node);
          return;
        }
        if (
          node.callee.type !== AST_NODE_TYPES.MemberExpression ||
          node.callee.computed ||
          node.callee.object.type !== AST_NODE_TYPES.Identifier ||
          node.callee.property.type !== AST_NODE_TYPES.Identifier ||
          node.callee.property.name !== "v4"
        ) {
          return;
        }
        const variable = resolve(node.callee.object);
        if (variable !== null && namespaceBindings.has(variable)) report(node);
      },
    };
  },
});
