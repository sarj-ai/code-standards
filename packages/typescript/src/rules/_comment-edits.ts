/**
 * @fileoverview _comment-edits — conservative source ranges for comment deletion.
 *
 */

import { splitIdentifier } from "./_comments.js";

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
  return ownLineCommentRemovalRange(text, comment);
}

/** Preserve neighboring tokens, line endings, and line-sensitive tool directives. */
export function ownLineCommentRemovalRange(
  text: string,
  comment: TSESTree.Comment,
): CommentRemoval | null {
  const lineStart = text.lastIndexOf("\n", Math.max(0, comment.range[0] - 1)) + 1;
  if (!/^[\t ]*$/u.test(text.slice(lineStart, comment.range[0]))) return null;
  const precedingLineStart = text.lastIndexOf("\n", Math.max(0, lineStart - 2)) + 1;
  if (/(?:eslint-disable-next-line|@ts-(?:expect-error|ignore)|prettier-ignore|biome-ignore|istanbul ignore next|[cv]8 ignore next)\b/iu.test(text.slice(precedingLineStart, lineStart))) return null;
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

/** Leave physical lines in place so next-line tooling keeps its original target. */
export function commentLineEndings(text: string, removal: CommentRemoval): string {
  return text.slice(...removal.range).replace(/[^\r\n]/gu, "");
}

/** Only an exact multiword member name qualifies; behavioral descriptions remain. */
export function exactMemberCommentRemovalRange(
  text: string,
  comment: TSESTree.Comment,
  key: TSESTree.Node,
): CommentRemoval | null {
  if (key.type !== "Identifier") return null;
  const body = comment.value.replace(/^\*+/u, "").replace(/^[\t ]*\*[\t ]?/gmu, "").trim()
    .replace(/^(?:the|a|an)\s+/iu, "").replace(/\.$/u, "");
  if (!/^[A-Za-z][A-Za-z ]*$/u.test(body) || /\b(?:not|no|never|only|must|shall|should|may|can|could|will|would|required|optional|if|unless|when|before|after|until|while|without|instead|true|false|null|undefined)\b/iu.test(body)) return null;
  const expected = splitIdentifier(key.name);
  const actual = body.split(/ +/u).flatMap(splitIdentifier);
  return expected.length >= 2 && expected.join(" ") === actual.join(" ")
    ? ownLineCommentRemovalRange(text, comment)
    : null;
}
