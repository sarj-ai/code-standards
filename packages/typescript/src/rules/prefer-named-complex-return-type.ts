/**
 * @fileoverview prefer-named-complex-return-type — large inline return contracts obscure reusable domain shapes.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-named-complex-return-type.test.ts
 */

import {
  AST_NODE_TYPES,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import { existingTypeAliasFix } from "./_existing-type-alias-fix.js";
import { isUnusedPrivateBinding } from "./_unused-private-binding.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "nameComplexReturnType";
type Options = [];

export const PREFER_NAMED_COMPLEX_RETURN_TYPE_DOCUMENTATION = {
  defaultLevel: "error",
  summary:
    "Prefer a named contract for structurally complex function return types.",
  rationale:
    "A large inline return annotation hides a reusable domain concept and makes signatures difficult to scan.",
  remediation:
    "Name the complex nested shape while preserving its generic wrappers and type parameters; reference the named contract from the return annotation.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Automatic fixes only reuse one existing exported nongeneric alias with exactly matching context-free type tokens for an unused private function declaration. Shared/public functions, missing or ambiguous aliases and locally dependent types remain manual.",
    "Only explicit object types with at least three members and unions with at least three object variants are reported.",
    "Any single-argument generic wrapper is traversed to find nested shapes, not assumed semantically transparent. Inferred return types are outside this rule; extraction is manual and must preserve locally bound type parameters with generic named contracts. Types depending on polymorphic this or a local value query are excluded.",
  ],
  examples: [
    {
      id: "named-result",
      title: "Name a multi-state result",
      outcome: "no-match",
      files: [
        {
          path: "src/queue.ts",
          source:
            "type ClaimResult = { state: 'idle' } | { state: 'waiting'; retryAt: number } | { state: 'claimed'; id: string }; export function claim(): ClaimResult { return { state: 'idle' }; }",
        },
      ],
      focusPath: "src/queue.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "inline-result",
      title: "Do not inline a multi-state result",
      outcome: "match",
      files: [
        {
          path: "src/queue.ts",
          source:
            "export function claim(): { state: 'idle' } | { state: 'waiting'; retryAt: number } | { state: 'claimed'; id: string } { return { state: 'idle' }; }",
        },
      ],
      focusPath: "src/queue.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Reuse the existing authored domain alias",
      outcome: "match",
      files: [
        {
          path: "src/autofix-example.ts",
          source:
            "export type Claim = { id: string; name: string; active: boolean }; function claim(): { id: string; name: string; active: boolean } { return { id: '', name: '', active: true }; }",
        },
      ],
      fixedFiles: [
        {
          path: "src/autofix-example.ts",
          source:
            "export type Claim = { id: string; name: string; active: boolean }; function claim(): Claim { return { id: '', name: '', active: true }; }",
        },
      ],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
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
  node: TSESTree.Node & {
    readonly returnType: TSESTree.TSTypeAnnotation | undefined;
  },
): void {
  const annotation = node.returnType?.typeAnnotation;
  if (
    annotation !== undefined &&
    isComplex(annotation) &&
    !hasValueDependency(annotation)
  ) {
    const name =
      node.type === AST_NODE_TYPES.FunctionDeclaration &&
      node.id !== null &&
      isUnusedPrivateBinding(
        context.sourceCode,
        node,
        node.id,
        context.filename,
      )
        ? existingTypeAliasFix(context.sourceCode, annotation)
        : null;
    context.report({
      node: annotation,
      messageId: "nameComplexReturnType",
      fix:
        name === null
          ? null
          : (fixer) =>
              fixer.replaceText(
                annotation,
                name +
                  context.sourceCode
                    .getText(annotation)
                    .replace(/[^\r\n]/gu, ""),
              ),
    });
  }
}

function hasValueDependency(node: TSESTree.Node): boolean {
  return (
    node.type === AST_NODE_TYPES.TSThisType ||
    node.type === AST_NODE_TYPES.TSTypeQuery ||
    forEachOwnAstChild(node, hasValueDependency)
  );
}

function isComplex(node: TSESTree.TypeNode): boolean {
  const type = unwrap(node);
  if (type.type === AST_NODE_TYPES.TSTypeLiteral)
    return type.members.length >= 3;
  if (type.type !== AST_NODE_TYPES.TSUnionType || type.types.length < 3)
    return false;
  return type.types.every(
    (member) => unwrap(member).type === AST_NODE_TYPES.TSTypeLiteral,
  );
}

export default createRule<Options, MessageIds>({
  name: "prefer-named-complex-return-type",
  documentation: PREFER_NAMED_COMPLEX_RETURN_TYPE_DOCUMENTATION,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Prefer a named contract for structurally complex function return types.",
    },
    schema: [],
    messages: {
      nameComplexReturnType:
        "Extract this structurally complex return annotation to a named type or interface.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isTestFile(context) ||
      isGeneratedFile(context, context.sourceCode.text)
    )
      return {};
    return {
      ArrowFunctionExpression: (node): void => report(context, node),
      FunctionDeclaration: (node): void => report(context, node),
      FunctionExpression: (node): void => report(context, node),
      TSDeclareFunction: (node): void => report(context, node),
      TSMethodSignature: (node): void => report(context, node),
    };
  },
});
