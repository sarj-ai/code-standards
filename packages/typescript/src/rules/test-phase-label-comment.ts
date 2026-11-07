/**
 * @fileoverview test-phase-label-comment — bare Arrange/Act/Assert labels restate structure the test should express.
 *
 * Port of the 18.x `test-phase-label-comment` rule. The rule is
 * untyped, so the port covers all of it.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/test-phase-label-comment.test.ts
 */

import type { Comment } from "@oxlint/plugins";

import { defineRule, type SourceCode } from "../types.js";
import { commentLineEndings, wholeLineRemovalRange } from "../utils/comment-edits.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";

const NAME = "test-phase-label-comment";

const PHASE_WORD = String.raw`arrange|act|assert(?:ion)?s?|given|when|then|exercise|execute|verif(?:y|ication)|cleanup|prepare|sanity(?:\s+check)?`;
const PHASE_RE = new RegExp(
  String.raw`^[-=~*_#.\s]{0,40}(?:${PHASE_WORD})(?:\s*(?:[/&+,|]|->|and)\s*(?:${PHASE_WORD}))*[-=~*_#.\s:;!–—]{0,40}$`,
  "iu",
);

function insideExpression(sourceCode: Readonly<SourceCode>, comment: Comment): boolean {
  const token = sourceCode.getTokenAfter(comment, { includeComments: false });
  if (token === null) return false;
  for (let node = sourceCode.getNodeByRangeIndex(token.range[0]); node !== null && node.type !== "Program"; node = parentOf(node)) {
    if (
      node.type === "ArrayExpression" ||
      node.type === "ObjectExpression" ||
      node.type === "CallExpression" ||
      node.type === "NewExpression"
    ) return node.loc.start.line < comment.loc.start.line;
    if (/Statement$/u.test(node.type) || /Declaration$/u.test(node.type)) return false;
  }
  return false;
}

function continuesProseRun(comments: readonly Comment[], index: number): boolean {
  const comment = comments[index];
  if (comment?.type !== "Line") return false;
  return [comments[index - 1], comments[index + 1]].some(
    (neighbor) =>
      neighbor?.type === "Line" &&
      Math.abs(neighbor.loc.start.line - comment.loc.start.line) === 1 &&
      !PHASE_RE.test(neighbor.value.trim()),
  );
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Tests must not use bare Arrange, Act, Assert, Given, When, or Then phase comments.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { removeLabel: "Bare test phase label — delete it and let the test names and helpers carry the structure." },
  },
  createOnce(context) {
    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        if (!isTestFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        return undefined;
      },
      Program(): void {
        const sourceCode = context.sourceCode;
        const comments = sourceCode.getAllComments();
        for (const [index, comment] of comments.entries()) {
          if (comment.type !== "Line" || !PHASE_RE.test(comment.value.trim())) continue;
          const removal = wholeLineRemovalRange(sourceCode.text, comment);
          if (removal === null || insideExpression(sourceCode, comment) || continuesProseRun(comments, index)) {
            continue;
          }
          const text = sourceCode.text;
          context.report({
            node: comment,
            messageId: "removeLabel",
            fix: (fixer) => {
              const endings = commentLineEndings(text, removal);
              return endings === null ? null : fixer.replaceTextRange([...(removal.range)], endings);
            },
          });
        }
      },
    };
  },
});
