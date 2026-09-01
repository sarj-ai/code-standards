/**
 * @fileoverview excessive-commentary — flag long standalone implementation narration.
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/excessive-commentary.test.ts
 */

import { AST_NODE_TYPES, type TSESTree, type TSESLint } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import {
  documentsTypedFunction,
  proseGroups,
} from "./_prose-budget.js";

type MessageIds = "excessive";
type Options = readonly [];

const ABSOLUTE_JSDOC_LINES = 10;
const ABSOLUTE_JSDOC_WORDS = 65;

export const EXCESSIVE_COMMENTARY_DOCUMENTATION = {
  summary: "Flag long standalone implementation commentary that should be expressed by code.",
  rationale: "Narrative implementation paragraphs compete with the code and can drift independently from behavior.",
  remediation: "Delete narration and clarify names, types, or structure; retain only durable constraints and external contracts.",
  category: "maintainability",
  limitations: [
    "Only an unattached file-header JSDoc block with at least ten non-empty lines and 65 words is inspected.",
    "Generated files, tests, scripts, stories, licenses, typed API documentation, and comments attached to declarations are excluded.",
  ],
  examples: [
    {
      id: "adapter-narration",
      title: "Adapter paragraph narrates application behavior",
      outcome: "match",
      files: [{
        path: "src/adapter.ts",
        source: [
          "/**",
          " * This file is the seam between the draft and backend models.",
          " * Everything above it uses the local application representation.",
          " * Everything below it uses a separately mirrored wire representation.",
          " * Field names use the API shape while the draft uses another shape.",
          " * This module translates every field between those representations.",
          " * The backend models changed several times during early development.",
          " * Each historical change required another edit in this adapter file.",
          " * The write half previously assembled several resources in one payload.",
          " * It now saves those resources separately through their own routes.",
          " * Clear contract types and generated clients should express this boundary.",
          " */",
          "import type { Draft } from './draft';",
        ].join("\n"),
      }],
      focusPath: "src/adapter.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "protocol-constraint",
      title: "Concrete wire compatibility constraint remains local",
      outcome: "no-match",
      files: [{
        path: "src/adapter.ts",
        source: [
          "// Legacy clients send `execution_phase` until API-812 is retired.",
          "// Keep conversion in GeneratedClientAdapter.",
          "export const phase = raw.execution_phase;",
        ].join("\n"),
      }],
      focusPath: "src/adapter.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function lineCount(text: string): number {
  return text.split("\n").filter((line) => line.trim().length > 0).length;
}

function wordCount(text: string): number {
  return text.trim().split(/\s+/u).filter(Boolean).length;
}

function isJSDoc(comment: TSESTree.Comment): boolean {
  return comment.type === "Block" && comment.value.startsWith("*");
}

function isFileHeader(sourceCode: Readonly<TSESLint.SourceCode>, comment: TSESTree.Comment): boolean {
  return sourceCode.getTokenBefore(comment, { includeComments: false }) === null;
}

function documentsTypeOrMember(
  sourceCode: Readonly<TSESLint.SourceCode>,
  comment: TSESTree.Comment,
): boolean {
  const token = sourceCode.getTokenAfter(comment, { includeComments: false });
  if (token === null || token.loc.start.line !== comment.loc.end.line + 1) return false;
  let node: TSESTree.Node | null | undefined = sourceCode.getNodeByRangeIndex(token.range[0]);
  while (node != null && node.type !== AST_NODE_TYPES.Program) {
    if (isTypedDeclaration(node)) return true;
    node = node.parent;
  }
  return false;
}

function isTypedDeclaration(node: TSESTree.Node): boolean {
  if (
    node.type === AST_NODE_TYPES.ExportNamedDeclaration ||
    node.type === AST_NODE_TYPES.ExportDefaultDeclaration
  ) {
    return node.declaration !== null && isTypedDeclaration(node.declaration);
  }
  return (
    node.type === AST_NODE_TYPES.TSInterfaceDeclaration ||
    node.type === AST_NODE_TYPES.TSTypeAliasDeclaration ||
    node.type === AST_NODE_TYPES.ClassDeclaration ||
    node.type === AST_NODE_TYPES.MethodDefinition ||
    node.type === AST_NODE_TYPES.TSMethodSignature ||
    node.type === AST_NODE_TYPES.TSPropertySignature
  );
}

export default createRule<Options, MessageIds>({
  name: "excessive-commentary",
  documentation: EXCESSIVE_COMMENTARY_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description: EXCESSIVE_COMMENTARY_DOCUMENTATION.summary,
    },
    schema: [],
    messages: {
      excessive: "Implementation comment is a prose wall — make the code self-documenting and keep only durable constraints.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      Program(): void {
        for (const group of proseGroups(context.filename, context.sourceCode)) {
          const lines = lineCount(group.text);
          const words = wordCount(group.text);
          if (isJSDoc(group.comment)) {
            if (
              isFileHeader(context.sourceCode, group.comment) &&
              lines >= ABSOLUTE_JSDOC_LINES &&
              words >= ABSOLUTE_JSDOC_WORDS &&
              !group.hasTypedTags &&
              !documentsTypedFunction(context.sourceCode, group.comment) &&
              !documentsTypeOrMember(context.sourceCode, group.comment)
            ) context.report({ node: group.comment, messageId: "excessive" });
          }
        }
      },
    };
  },
});
