/**
 * @fileoverview no-long-comment — catch only unusually large, unstructured JSDoc blocks.
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-long-comment.test.ts
 */

import { AST_NODE_TYPES, type TSESTree, type TSESLint } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import {
  documentsTypedFunction,
  hasDocumentationStructure,
  hasTechnicalAnchor,
  proseGroups,
  sentenceUnits,
} from "./_prose-budget.js";

type MessageIds = "tooLong";
type Options = readonly [];

export const noLongCommentDocumentation = {
  summary: "Flag unusually large unstructured JSDoc blocks in implementation code.",
  rationale: "Large narrative comments become stale and obscure the local facts that belong beside the code.",
  remediation: "Keep only durable local constraints and express the remaining behavior in code.",
  category: "maintainability",
  limitations: ["Only JSDoc blocks are inspected; structured API docs, tests, scripts, generated files, and versioned dependencies are excluded."],
  examples: [
    {
      id: "structured-jsdoc",
      title: "Paragraphs separate a component's durable constraints",
      outcome: "no-match",
      files: [{
        path: "src/composer.ts",
        source: [
          "/**",
          " * Shared composer.",
          " *",
          " * It serves the room. It serves task comments. It stays visually calm. It accepts attachments.",
          " *",
          " * The `tone` prop supplies task styling. The `leadingTools` prop supplies controls.",
          " * The parent owns uploads. The component owns focus.",
          " */",
          "",
          "export const Composer = forwardRef(function Composer() { return null; });",
        ].join("\n"),
      }],
      focusPath: "src/composer.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "prose-wall",
      title: "One paragraph narrates a chart's design history",
      outcome: "match",
      files: [{
        path: "src/chart.ts",
        source: `/**
 * The ports chart shows arrivals and departures across the network.
 * It was originally a line chart, but the lines crossed too often.
 * Bars make adjacent ports easier to compare at a glance.
 * The axis starts at zero so visual differences stay proportional.
 * A single series uses the site navy for brand consistency.
 * Empty ports use a neutral ink so missing traffic remains visible.
 * Tooltip values repeat the units shown on the vertical axis.
 * The chart intentionally keeps labels horizontal on wide screens.
 */
export function PortBars() { return null; }`,
      }],
      focusPath: "src/chart.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const EXCESSIVE_SENTENCE_COUNT = 8;
const EXCESSIVE_WORD_COUNT = 120;
const PROSE_WORD_RE = /[\p{L}\p{N}][\p{L}\p{N}'’-]*/gu;
const VERSIONED_DEPENDENCY_TREE_RE =
  /(?:^|\/)lib\/[^/]*-?v?\d+\.\d+(?:\.\d+)?[^/]*\//iu;

function documentsTypeOrMember(
  sourceCode: Readonly<TSESLint.SourceCode>,
  comment: TSESTree.Comment,
): boolean {
  const token = sourceCode.getTokenAfter(comment, { includeComments: false });
  if (token === null || token.loc.start.line !== comment.loc.end.line + 1) return false;
  let node: TSESTree.Node | null | undefined = sourceCode.getNodeByRangeIndex(token.range[0]);
  while (node != null && node.type !== AST_NODE_TYPES.Program) {
    if (
      node.type === AST_NODE_TYPES.TSInterfaceDeclaration ||
      node.type === AST_NODE_TYPES.TSTypeAliasDeclaration ||
      node.type === AST_NODE_TYPES.ClassDeclaration ||
      node.type === AST_NODE_TYPES.MethodDefinition ||
      node.type === AST_NODE_TYPES.TSMethodSignature ||
      node.type === AST_NODE_TYPES.TSPropertySignature
    ) return true;
    node = node.parent;
  }
  return false;
}

function wordUnits(text: string): number {
  return text.match(PROSE_WORD_RE)?.length ?? 0;
}

export default createRule<Options, MessageIds>({
  name: "no-long-comment",
  documentation: noLongCommentDocumentation,
  meta: {
    type: "suggestion",
    docs: { description: "Flag unusually large unstructured JSDoc blocks in implementation code." },
    schema: [],
    messages: {
      tooLong: "Comment is an unusually large prose block — keep the local facts and clarify the code itself.",
    },
  },
  defaultOptions: [],
  create(context) {
    const normalizedFilename = context.filename.replaceAll("\\", "/");
    if (VERSIONED_DEPENDENCY_TREE_RE.test(normalizedFilename)) return {};
    return {
      Program(): void {
        for (const group of proseGroups(context.filename, context.sourceCode)) {
          if (
            group.comment.type !== "Block" ||
            !group.comment.value.startsWith("*") ||
            group.hasTypedTags ||
            hasDocumentationStructure(group.text) ||
            hasTechnicalAnchor(group.text) ||
            documentsTypedFunction(context.sourceCode, group.comment) ||
            documentsTypeOrMember(context.sourceCode, group.comment) ||
            sentenceUnits(group.text) < EXCESSIVE_SENTENCE_COUNT &&
            wordUnits(group.text) < EXCESSIVE_WORD_COUNT
          ) continue;
          context.report({ node: group.comment, messageId: "tooLong" });
        }
      },
    };
  },
});
