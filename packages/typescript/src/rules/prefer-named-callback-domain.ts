/**
 * @fileoverview prefer-named-callback-domain — prefer named literal domains in public callback contracts.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-named-callback-domain.test.ts
 */
import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "nameCallbackDomain";
type Options = [];

export const PREFER_NAMED_CALLBACK_DOMAIN_DOCUMENTATION = {
  summary: "Name literal-union domains used by callbacks in exported contracts.",
  rationale: "An inline callback domain hides a reusable vocabulary at the point where callers and implementations must agree.",
  remediation: "Extract the literal union to a named type and use that type in the callback parameter.",
  category: "maintainability",
  limitations: ["Only callback types nested in an exported type alias or exported interface are reported."],
  examples: [
    { id: "named-domain", title: "Name the callback domain", outcome: "no-match", files: [{ path: "src/options.ts", source: "export type Boundary = 'seeded' | 'queued'; export interface Options { done?: (boundary: Boundary) => void; }" }], focusPath: "src/options.ts", expectedCount: 0, public: true },
    { id: "inline-domain", title: "Do not inline a public callback domain", outcome: "match", files: [{ path: "src/options.ts", source: "export interface Options { done?: (boundary: 'seeded' | 'queued') => void; }" }], focusPath: "src/options.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function isLiteralUnion(node: TSESTree.TypeNode): boolean {
  return node.type === AST_NODE_TYPES.TSUnionType && node.types.length >= 2 &&
    node.types.every((part) => part.type === AST_NODE_TYPES.TSLiteralType);
}

function exportedContract(node: TSESTree.Node): boolean {
  let current: TSESTree.Node | undefined = node;
  while (current !== undefined) {
    if (current.type === AST_NODE_TYPES.ExportNamedDeclaration) return true;
    if (current.type === AST_NODE_TYPES.Program) return false;
    current = current.parent ?? undefined;
  }
  return false;
}

export default createRule<Options, MessageIds>({
  name: "prefer-named-callback-domain",
  documentation: PREFER_NAMED_CALLBACK_DOMAIN_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: "Name literal-union domains used by callbacks in exported contracts." },
    schema: [],
    messages: { nameCallbackDomain: "Extract this inline callback literal union to a named domain type." },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    return {
      TSFunctionType(node): void {
        if (!exportedContract(node)) return;
        for (const parameter of node.params) {
          if (parameter.type !== AST_NODE_TYPES.TSParameterProperty && parameter.typeAnnotation !== undefined && isLiteralUnion(parameter.typeAnnotation.typeAnnotation)) {
            context.report({ node: parameter.typeAnnotation.typeAnnotation, messageId: "nameCallbackDomain" });
          }
        }
      },
    } satisfies TSESLint.RuleListener;
  },
});
