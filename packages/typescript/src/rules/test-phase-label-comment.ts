/**
 * @fileoverview test-phase-label-comment — bare phase labels narrate test structure without adding behavior.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/test-phase-label-comment.test.ts
 */

import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { wholeLineRemovalRange } from "./_comment-edits.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "removeLabel";
type Options = readonly [];

const PHASE_WORD = String.raw`arrange|act|assert(?:ion)?s?|given|when|then|exercise|execute|verif(?:y|ication)|cleanup|prepare|sanity(?:\s+check)?`;
const PHASE_RE = new RegExp(
  String.raw`^[-=~*_#.\s]{0,40}(?:${PHASE_WORD})(?:\s*(?:[/&+,|]|->|and)\s*(?:${PHASE_WORD}))*[-=~*_#.\s:;!–—]{0,40}$`,
  "iu",
);

export const testPhaseLabelCommentDocumentation = {
  summary: "Tests must not use bare Arrange, Act, Assert, Given, When, or Then phase comments.",
  rationale: "Phase labels narrate test structure without explaining behavior and often hide unclear names or oversized tests.",
  remediation: "Delete the label; if the phases remain hard to follow, extract a named helper or split the test.",
  category: "testing",
  autofix: "safe",
  limitations: [
    "Only standalone line comments in recognized test files are checked.",
    "Comments inside bracketed expressions or containing words outside the bounded phase grammar are preserved.",
  ],
  examples: [
    {
      id: "behavioral-comment",
      title: "Behavioral consequence is retained",
      outcome: "no-match",
      files: [{ path: "widget.test.ts", source: "// Then the retry loop would spin forever.\nexpect(run()).toBe(true);" }],
      focusPath: "widget.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "bare-phase-label",
      title: "Bare phase label is removed",
      outcome: "match",
      files: [{ path: "widget.test.ts", source: "// Arrange\nconst widget = makeWidget();" }],
      focusPath: "widget.test.ts",
      expectedCount: 1,
      fixedFiles: [{ path: "widget.test.ts", source: "const widget = makeWidget();" }],
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function insideExpression(sourceCode: Readonly<TSESLint.SourceCode>, comment: TSESTree.Comment): boolean {
  const token = sourceCode.getTokenAfter(comment, { includeComments: false });
  if (token === null) return false;
  let node: TSESTree.Node | null | undefined = sourceCode.getNodeByRangeIndex(token.range[0]);
  while (node != null && node.type !== AST_NODE_TYPES.Program) {
    if (
      node.type === AST_NODE_TYPES.ArrayExpression ||
      node.type === AST_NODE_TYPES.ObjectExpression ||
      node.type === AST_NODE_TYPES.CallExpression ||
      node.type === AST_NODE_TYPES.NewExpression
    ) return node.loc.start.line < comment.loc.start.line;
    if (/Statement$/u.test(node.type) || /Declaration$/u.test(node.type)) return false;
    node = node.parent;
  }
  return false;
}

function continuesProseRun(comments: readonly TSESTree.Comment[], index: number): boolean {
  const comment = comments[index];
  if (comment?.type !== "Line") return false;
  return [comments[index - 1], comments[index + 1]].some(
    (neighbor) =>
      neighbor?.type === "Line" &&
      Math.abs(neighbor.loc.start.line - comment.loc.start.line) === 1 &&
      !PHASE_RE.test(neighbor.value.trim()),
  );
}

export default createRule<Options, MessageIds>({
  name: "test-phase-label-comment",
  documentation: testPhaseLabelCommentDocumentation,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: testPhaseLabelCommentDocumentation.summary },
    schema: [],
    messages: { removeLabel: "Bare test phase label — delete it and let the test names and helpers carry the structure." },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    return {
      Program(): void {
        const comments = context.sourceCode.getAllComments();
        for (const [index, comment] of comments.entries()) {
          if (comment.type !== "Line" || !PHASE_RE.test(comment.value.trim())) continue;
          const removal = wholeLineRemovalRange(context.sourceCode.text, comment);
          if (removal === null || insideExpression(context.sourceCode, comment) || continuesProseRun(comments, index)) {
            continue;
          }
          context.report({
            node: comment,
            messageId: "removeLabel",
            fix: (fixer) => fixer.removeRange(removal.range),
          });
        }
      },
    };
  },
});
