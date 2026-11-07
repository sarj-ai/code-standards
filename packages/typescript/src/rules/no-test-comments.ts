/**
 * @fileoverview no-test-comments — Express test behavior through names, fixtures and assertions instead of prose comments.
 *
 * Port of the 18.x `no-test-comments` rule. File gates move to
 * `before()`; the comment scan and fixes are unchanged.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-test-comments.test.ts
 */

import type { Comment, Fix, Fixer } from "@oxlint/plugins";

import { defineRule, type SourceCode } from "../types.js";
import { commentLineEndings, ownLineCommentRemovalRange, trailingCommentRemovalRange } from "../utils/comment-edits.js";
import { docsUrl } from "../utils/docs-url.js";
import { isFrontendSource } from "../utils/is-frontend-source.js";
import { isGeneratedFile, isTestFile, scopedFilename } from "../utils/paths.js";

interface Options { readonly allFiles?: boolean }

const DIRECTIVE = /^(?:eslint(?:-\S+)?\b|(?:biome|oxlint|jshint|jslint|c8|v8|istanbul|vitest|prettier|dprint)\b|@(?:ts-(?:check|nocheck|expect-error|ignore)|vitest-environment|jest-environment|jsx\w*|license|preserve)\b|[#!]\s*__(?:PURE|NO_SIDE_EFFECTS)__|\/\s*<(?:reference|amd-module|amd-dependency)\b)/u;
const BEHAVIORAL_DIRECTIVE = /(?:[@#]__(?:PURE|NO_SIDE_EFFECTS)__|@vite-ignore\b|\bwebpack(?:ChunkName|Mode|Exports|FetchPriority|Include|Exclude|Prefetch|Preload|Ignore)\s*:)/u;
const LEGAL = /(?:^|\n)\s*\*?\s*(?:Copyright\b|SPDX-License-Identifier:|Licensed under\b|@license\b|@preserve\b)/iu;
const TYPE_CONTRACT = /@(?:type|typedef|template|param|returns?|satisfies|callback|overload|implements|extends|augments|enum|this|import)\b/u;

const DETECT_SECRETS_COMMENT_MARKERS = [
  { start: "#", end: "" },
  { start: "//", end: "" },
  { start: "/\\*", end: " *\\*/" },
  { start: "'", end: "" },
  { start: "--", end: "" },
  { start: "<!--[# \\t]*?", end: " *?-->" },
] as const;
const DETECT_SECRETS_PRAGMAS = DETECT_SECRETS_COMMENT_MARKERS.flatMap(({ start, end }) => [
  { nextLine: false, pattern: new RegExp(`[ \\t]*${start} *pragma: ?(?:allow|white)list[ -]secret[^\\n]*?${end}[ \\t]*(?![\\s\\S])`, "u") },
  { nextLine: true, pattern: new RegExp(`^[ \\t]*${start} *pragma: ?allowlist[ -]nextline[ -]secret[^\\n]*?${end}[ \\t]*(?![\\s\\S])`, "u") },
]);
const PYTHON_WHITESPACE = /\p{White_Space}/u;
const PYTHON_EXTRA_WHITESPACE: ReadonlySet<string> = new Set(["\u001c", "\u001d", "\u001e", "\u001f"]);
const TEST_FRAMEWORKS: readonly string[] = ["vitest", "@jest/globals", "@playwright/test", "bun:test", "node:test"];

export interface TestCommentFile {
  readonly filename: string;
  readonly cwd: string;
  readonly sourceCode: Pick<SourceCode, "ast">;
}

/** True when no-test-comments, not no-frontend-comments, owns this file's comments. */
export function ownsTestComments(context: TestCommentFile): boolean {
  if (!isTestFile(context)) return false;
  const filename = scopedFilename(context);
  const unambiguous = /(?:^|\/)(?:tests?|__tests__|fixtures|__fixtures__|__mocks__)\//u.test(filename) || /\.(?:test|spec|e2e|integration)\.[cm]?[jt]sx?$/u.test(filename);
  const framework = context.sourceCode.ast.body.some(statement => statement.type === "ImportDeclaration" && statement.importKind !== "type" &&
    (statement.specifiers.length === 0 || statement.specifiers.some(specifier => specifier.type !== "ImportSpecifier" || specifier.importKind !== "type")) &&
    TEST_FRAMEWORKS.includes(statement.source.value));
  return unambiguous || framework;
}

function legalNoticeComments(comments: readonly Comment[]): ReadonlySet<Comment> {
  const legal = new Set<Comment>();
  for (const [index, comment] of comments.entries()) {
    if (legal.has(comment) || comment.type !== "Line" || !LEGAL.test(comment.value)) continue;
    legal.add(comment);
    for (const direction of [-1, 1]) {
      let previous = comment;
      for (let next = index + direction; next >= 0 && next < comments.length; next += direction) {
        const neighbor = comments[next];
        if (neighbor?.type !== "Line" || Math.abs(neighbor.loc.start.line - previous.loc.start.line) !== 1) break;
        legal.add(neighbor);
        previous = neighbor;
      }
    }
  }
  return legal;
}

/** Directives, legal notices, type contracts and secret-scanner pragmas stay outside frontend sources. */
function isExempt(comment: Comment, text: string, legal: ReadonlySet<Comment>): boolean {
  return DIRECTIVE.test(comment.value.trim().replace(/^\*\s*/u, "")) || BEHAVIORAL_DIRECTIVE.test(comment.value) ||
    LEGAL.test(comment.value) || legal.has(comment) || TYPE_CONTRACT.test(comment.value) || hasDetectSecretsPragma(comment, text);
}

function hasDetectSecretsPragma(comment: Comment, text: string): boolean {
  if (!comment.value.includes("pragma:")) return false;
  let lineStart = Math.max(text.lastIndexOf("\r", comment.range[0] - 1), text.lastIndexOf("\n", comment.range[0] - 1)) + 1;
  const readerLineEndings = /\r\n?|\n/gu;
  readerLineEndings.lastIndex = lineStart;
  while (lineStart < comment.range[1]) {
    const ending = readerLineEndings.exec(text);
    const lineEnd = ending?.index ?? text.length;
    if (hasPragmaInReaderLine(comment, text.slice(lineStart, lineEnd), lineStart)) return true;
    lineStart = lineEnd + (ending?.[0].length ?? 1);
  }
  return false;
}

function hasPragmaInReaderLine(comment: Comment, rawLine: string, lineStart: number): boolean {
  const sameLine = stripPythonTrailingWhitespace(rawLine);
  for (const { nextLine, pattern } of DETECT_SECRETS_PRAGMAS) {
    const column = nextLine ? 0 : Math.max(0, comment.range[0] - lineStart);
    const match = pattern.exec((nextLine ? rawLine : sameLine).slice(column));
    if (match === null) continue;
    const pragmaStart = lineStart + column + match.index + match[0].indexOf("pragma:");
    if (pragmaStart >= comment.range[0] && pragmaStart < comment.range[1]) return true;
  }
  return false;
}

function stripPythonTrailingWhitespace(value: string): string {
  let end = value.length;
  while (end > 0) {
    const character = value.charAt(end - 1);
    if (!PYTHON_WHITESPACE.test(character) && !PYTHON_EXTRA_WHITESPACE.has(character)) break;
    end--;
  }
  return value.slice(0, end);
}

function commentRemoval(fixer: Fixer, sourceCode: SourceCode, comment: Comment): Fix | null {
  const text = sourceCode.text;
  const own = ownLineCommentRemovalRange(text, comment);
  if (own !== null) {
    const ownEndings = commentLineEndings(text, own);
    return ownEndings === null ? null : preserveLineTerminators(text, fixer.replaceTextRange([...own.range], ownEndings));
  }
  const trailing = trailingCommentRemovalRange(text, comment);
  if (trailing !== null) return preserveLineTerminators(text, fixer.replaceTextRange([...trailing.range], ""));
  const endings = sourceCode.getText(comment).replace(/[^\r\n\u2028\u2029]/gu, "");
  if (endings.length > 0) {
    let start = comment.range[0];
    while (start > 0 && /[\t ]/u.test(text[start - 1] ?? "")) start--;
    return preserveLineTerminators(text, fixer.replaceTextRange([start, comment.range[1]], endings));
  }
  const before = text[comment.range[0] - 1] ?? "";
  const after = text[comment.range[1]] ?? "";
  const separator = before.length > 0 && after.length > 0 && !/\s/u.test(before + after) ? " " : "";
  return preserveLineTerminators(text, fixer.replaceText(comment, separator));
}

function preserveLineTerminators(text: string, edit: Fix): Fix | null {
  const neighbor = Math.max(0, edit.range[0] - 1);
  const original = text.slice(neighbor, edit.range[1] + 1).match(/\r\n|[\r\n\u2028\u2029]/gu) ?? [];
  const rendered = (text.slice(neighbor, edit.range[0]) + edit.text + text.slice(edit.range[1], edit.range[1] + 1))
    .match(/\r\n|[\r\n\u2028\u2029]/gu) ?? [];
  return original.length === rendered.length && original.every((ending, position) => ending === rendered[position]) ? edit : null;
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Express test behavior through names, fixtures and assertions instead of prose comments.",
      url: docsUrl("no-test-comments"),
    },
    schema: [{ type: "object", properties: { allFiles: { description: "Check every eligible test file without requiring frontend framework ownership.", type: "boolean" } }, additionalProperties: false }],
    messages: { testComment: "Express this explanation in the test name, fixture or assertion, then remove the comment." },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let frontend = false;
    return {
      before() {
        sourceCode = context.sourceCode;
        const file = { filename: context.filename, cwd: context.cwd, sourceCode };
        if (!ownsTestComments(file) || isGeneratedFile(file, sourceCode.text)) return false;
        const [options] = context.options as unknown as readonly [Options?];
        frontend = options?.allFiles === true || isFrontendSource(file);
        return undefined;
      },
      Program(): void {
        const comments = sourceCode.getAllComments();
        const legal = frontend ? null : legalNoticeComments(comments);
        for (const comment of comments) {
          if (legal !== null && isExempt(comment, sourceCode.text, legal)) continue;
          context.report({
            node: comment,
            messageId: "testComment",
            fix: fixer => frontend ? null : commentRemoval(fixer, sourceCode, comment),
          });
        }
      },
    };
  },
});
