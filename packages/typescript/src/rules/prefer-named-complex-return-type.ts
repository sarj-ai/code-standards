/**
 * @fileoverview prefer-named-complex-return-type — large inline return contracts obscure reusable domain shapes.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-named-complex-return-type.test.ts
 */

import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "nameComplexReturnType";
type Options = [];

export const PREFER_NAMED_COMPLEX_RETURN_TYPE_DOCUMENTATION = {
  summary: "Prefer a named contract for structurally complex function return types.",
  rationale: "A large inline return annotation hides a reusable domain concept and makes signatures difficult to scan.",
  remediation: "Extract the return annotation to a named type or interface and reference that contract from the signature.",
  category: "maintainability",
  limitations: [
    "Only explicit object types with at least three members and unions with at least three object variants are reported.",
    "Generic wrappers such as Promise and Readonly are unwrapped one level at a time; inferred return types are outside this rule.",
  ],
  examples: [
    { id: "named-result", title: "Name a multi-state result", outcome: "no-match", files: [{ path: "src/queue.ts", source: "type ClaimResult = { state: 'idle' } | { state: 'waiting'; retryAt: number } | { state: 'claimed'; id: string }; export function claim(): ClaimResult { return { state: 'idle' }; }" }], focusPath: "src/queue.ts", expectedCount: 0, public: true },
    { id: "inline-result", title: "Do not inline a multi-state result", outcome: "match", files: [{ path: "src/queue.ts", source: "export function claim(): { state: 'idle' } | { state: 'waiting'; retryAt: number } | { state: 'claimed'; id: string } { return { state: 'idle' }; }" }], focusPath: "src/queue.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function unwrap(node: TSESTree.TypeNode): TSESTree.TypeNode {
  if (
    node.type === AST_NODE_TYPES.TSTypeReference &&
    node.typeArguments?.params.length === 1
  ) {
    const [inner] = node.typeArguments.params;
    if (inner !== undefined) return unwrap(inner);
  }
  return node;
}

function report(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  node: TSESTree.Node & { readonly returnType: TSESTree.TSTypeAnnotation | undefined },
): void {
  const annotation = node.returnType?.typeAnnotation;
  if (annotation !== undefined && isComplex(annotation)) {
    context.report({ node: annotation, messageId: "nameComplexReturnType" });
  }
}

function isComplex(node: TSESTree.TypeNode): boolean {
  const type = unwrap(node);
  if (type.type === AST_NODE_TYPES.TSTypeLiteral) return type.members.length >= 3;
  if (type.type !== AST_NODE_TYPES.TSUnionType || type.types.length < 3) return false;
  return type.types.every((member) => unwrap(member).type === AST_NODE_TYPES.TSTypeLiteral);
}

export default createRule<Options, MessageIds>({
  name: "prefer-named-complex-return-type",
  documentation: PREFER_NAMED_COMPLEX_RETURN_TYPE_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: "Prefer a named contract for structurally complex function return types." },
    schema: [],
    messages: {
      nameComplexReturnType: "Extract this structurally complex return annotation to a named type or interface.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    return {
      ArrowFunctionExpression: (node): void => report(context, node),
      FunctionDeclaration: (node): void => report(context, node),
      FunctionExpression: (node): void => report(context, node),
      TSDeclareFunction: (node): void => report(context, node),
      TSMethodSignature: (node): void => report(context, node),
    };
  },
});
