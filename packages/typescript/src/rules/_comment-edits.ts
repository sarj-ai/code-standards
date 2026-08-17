/**
 * @fileoverview _comment-edits — conservative source ranges for comment-deletion suggestions.
 *
 */

import { type TSESTree } from "@typescript-eslint/utils";

type RemovalRange = readonly [number, number];

export interface CommentRemoval {
  readonly range: RemovalRange;
}

function physicalLineEnd(text: string, offset: number): number {
  const newline = text.indexOf("\n", offset);
  return newline < 0 ? text.length : newline;
}

function contentLineEnd(text: string, offset: number): number {
  const end = physicalLineEnd(text, offset);
  return end > offset && text[end - 1] === "\r" ? end - 1 : end;
}

/** Delete an own-line comment, its indentation, and exactly one line ending. */
export function wholeLineRemovalRange(
  text: string,
  comment: TSESTree.Comment,
): CommentRemoval | null {
  if (comment.loc.start.line !== comment.loc.end.line) return null;
  const lineStart = text.lastIndexOf("\n", Math.max(0, comment.range[0] - 1)) + 1;
  if (!/^[\t ]*$/u.test(text.slice(lineStart, comment.range[0]))) return null;
  const contentEnd = contentLineEnd(text, comment.range[1]);
  if (!/^[\t ]*$/u.test(text.slice(comment.range[1], contentEnd))) return null;
  const physicalEnd = physicalLineEnd(text, comment.range[1]);
  return { range: [lineStart, physicalEnd < text.length ? physicalEnd + 1 : physicalEnd] };
}

/** Delete a trailing comment and adjacent horizontal whitespace, preserving EOL. */
export function trailingCommentRemovalRange(
  text: string,
  comment: TSESTree.Comment,
): CommentRemoval | null {
  if (comment.loc.start.line !== comment.loc.end.line) return null;
  const contentEnd = contentLineEnd(text, comment.range[1]);
  if (!/^[\t ]*$/u.test(text.slice(comment.range[1], contentEnd))) return null;
  let start = comment.range[0];
  while (start > 0 && (text[start - 1] === " " || text[start - 1] === "\t")) {
    start -= 1;
  }
  return { range: [start, contentEnd] };
}
