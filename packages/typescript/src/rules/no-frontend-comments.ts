/**
 * @fileoverview no-frontend-comments — express frontend behavior through executable code.
 *
 * Port of the 18.x `no-frontend-comments` rule. File gates move to
 * `before()`; JSX ranges are reset per file.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-frontend-comments.test.ts
 */

import type { Comment } from "@oxlint/plugins";

import { defineRule, type ESTree, type SourceCode } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isFrontendSource } from "../utils/is-frontend-source.js";
import { isGeneratedFile } from "../utils/paths.js";
import { ownsTestComments } from "./no-test-comments.js";

interface Options { readonly allFiles?: boolean }

type SourceRange = readonly [number, number];

const LINE_TERMINATOR = /[\r\n\u2028\u2029]/u;

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Express frontend behavior through code instead of prose comments.",
      url: docsUrl("no-frontend-comments"),
    },
    schema: [{ type: "object", properties: { allFiles: { description: "Check comments without requiring frontend framework ownership.", type: "boolean" } }, additionalProperties: false }],
    messages: { noFrontendComments: "Frontend comments are prohibited; express the behavior in names, types or code and review any directive or legal contract before removing it." },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    /** Outermost JSX ranges in source order; nested JSX lies inside the last one. */
    let jsxRanges: SourceRange[] = [];
    function captureJSX(node: ESTree.JSXElement | ESTree.JSXFragment): void {
      const previous = jsxRanges.at(-1);
      if (previous === undefined || node.range[0] >= previous[1]) jsxRanges.push(node.range);
    }
    return {
      before() {
        sourceCode = context.sourceCode;
        const file = { filename: context.filename, cwd: context.cwd, sourceCode };
        if (isGeneratedFile(file, sourceCode.text) || ownsTestComments(file)) return false;
        jsxRanges = [];
        return undefined;
      },
      JSXElement: captureJSX,
      JSXFragment: captureJSX,
      "Program:exit"(): void {
        const comments = sourceCode.getAllComments();
        const [options] = context.options as unknown as readonly [Options?];
        if (comments.length === 0 || !(options?.allFiles === true || isFrontendSource(context))) return;
        const ranges = emptyCommentRanges(comments, jsxRanges);
        for (const comment of comments) context.report({
          node: comment,
          messageId: "noFrontendComments",
          fix(fixer) {
            return ranges.has(comment) ? fixer.replaceTextRange(comment.range, " ") : null;
          },
        });
      },
    };
  },
});

/** Blank single-line comments outside JSX, whose removal leaves the code unchanged. */
function emptyCommentRanges(comments: readonly Comment[], jsxRanges: readonly SourceRange[]): ReadonlySet<Comment> {
  const empty = new Set<Comment>();
  let jsxIndex = 0;
  for (const comment of comments) {
    const [start, end] = comment.range;
    let jsx = jsxRanges[jsxIndex];
    while (jsx !== undefined && jsx[1] <= start) { jsxIndex += 1; jsx = jsxRanges[jsxIndex]; }
    if (jsx !== undefined && start < jsx[1] && end > jsx[0]) continue;
    if (isEmptyComment(comment)) empty.add(comment);
  }
  return empty;
}

function isEmptyComment(comment: Comment): boolean {
  return comment.type !== "Shebang" && comment.value.trim() === "" && !LINE_TERMINATOR.test(comment.value);
}
