/**
 * @fileoverview excessive-commentary — flag long standalone implementation narration.
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/excessive-commentary.test.ts
 */

import { AST_NODE_TYPES, type TSESTree, type TSESLint } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import {
  documentsTypedFunction,
  hasTechnicalAnchor,
  proseGroups,
} from "./_prose-budget.js";

type MessageIds = "excessive";
type Options = readonly [];

const MIN_LINES = 4;
const MIN_WORDS = 28;
const ABSOLUTE_JSDOC_LINES = 10;
const ABSOLUTE_JSDOC_WORDS = 65;
const RATIONALE_RE = /\b(?:because|otherwise|therefore|must|never|cannot|can't|required?|invariant|compatibility|security|race|atomic|deadlock|rollback|lock|data loss)\b|\bso\s+(?:that|a|an|the|this|it|we|they)\b/iu;
const BULLET_RE = /^\s*(?:[-*+] |\d+[.)] )/mu;

export const EXCESSIVE_COMMENTARY_DOCUMENTATION = {
  summary: "Flag long standalone implementation commentary that should be expressed by code.",
  rationale: "Narrative implementation paragraphs compete with the code and can drift independently from behavior.",
  remediation: "Delete narration and clarify names, types, or structure; retain only durable constraints and external contracts.",
  category: "maintainability",
  limitations: [
    "Standalone comments are inspected at four non-empty lines and 28 words; unattached file-level JSDoc is inspected at ten lines and 80 words.",
    "Generated files, tests, scripts, stories, directives, licenses, typed API documentation, structured lists, rationale markers, and concrete technical anchors are excluded.",
  ],
  examples: [
    {
      id: "adapter-narration",
      title: "Adapter paragraph narrates application behavior",
      outcome: "match",
      files: [{
        path: "src/adapter.ts",
        source: [
          "// Field names use the API shape at this layer.",
          "// The draft uses the application shape everywhere else.",
          "// This function translates every field between those representations.",
          "// Keeping both spellings here makes future additions easy to miss.",
          "export const adapt = (raw: Raw): Draft => transform(raw);",
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
              lines >= ABSOLUTE_JSDOC_LINES &&
              words >= ABSOLUTE_JSDOC_WORDS &&
              !group.hasTypedTags &&
              !documentsTypedFunction(context.sourceCode, group.comment) &&
              !documentsTypeOrMember(context.sourceCode, group.comment)
            ) context.report({ node: group.comment, messageId: "excessive" });
            continue;
          }
          if (
            lines < MIN_LINES ||
            words < MIN_WORDS ||
            BULLET_RE.test(group.text) ||
            hasTechnicalAnchor(group.text) ||
            RATIONALE_RE.test(group.text)
          ) continue;
          context.report({ node: group.comment, messageId: "excessive" });
        }
      },
    };
  },
});
