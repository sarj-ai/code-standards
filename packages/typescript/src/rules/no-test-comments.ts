/**
 * @fileoverview no-test-comments — Express test behavior through names, fixtures and assertions instead of prose comments.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-test-comments.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { commentLineEndings, ownLineCommentRemovalRange, trailingCommentRemovalRange } from "./_comment-edits.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile, scopedFilename } from "./_paths.js";

export const NO_TEST_COMMENTS_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Express test behavior through names, fixtures and assertions instead of prose comments.",
  rationale: "Test comments duplicate or obscure behavior that executable setup and assertions should communicate.",
  remediation: "Move the explanation into a descriptive test or helper name, then remove the comment. Preserve required legal notices and executable tool directives.",
  category: "testing",
  autofix: "safe",
  limitations: [
    "Checks actual line and block comment tokens in recognized maintained test files, including test fixtures; strings and template text remain unchanged. Generated/vendor files are excluded.",
    "Legal notices, shebangs, TypeScript triple-slash references, coverage/build annotations and explicit lint/type/test/formatter directives remain allowed. Executable detect-secrets 1.5.0 allowlist/whitelist pragmas retain its case-sensitive delimiter, spacing, physical-line and next-line grammar; arbitrary pragma prose remains ordinary commentary. Rationale on an executable directive remains the owning tool's responsibility.",
    "The automatic fix removes comments and adjacent padding while retaining every line ending and necessary token boundary; it does not rename tests or remove executable statements. Bare integration/e2e directories and ambiguous hyphen/underscore test basenames require another concrete test-path signal or a runtime testing-framework import; ordinary production integration modules and rule implementations ending in -test are preserved.",
  ],
  examples: [
    { id: "narrated-assertion", title: "Put behavior in the test name", outcome: "match", files: [{ path: "src/request.test.ts", source: "expect(result.status).toBe(409); // Confirm the rejected request\n" }], fixedFiles: [{ path: "src/request.test.ts", source: "expect(result.status).toBe(409);\n" }], focusPath: "src/request.test.ts", expectedCount: 1, public: true },
    { id: "named-behavior", title: "The assertion expresses the behavior", outcome: "no-match", files: [{ path: "src/request.test.ts", source: "expect(result.status).toBe(409);" }], focusPath: "src/request.test.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

const DIRECTIVE = /^(?:eslint(?:-\S+)?\b|(?:biome|oxlint|jshint|jslint|c8|v8|istanbul|vitest|prettier|dprint)\b|@(?:ts-(?:check|nocheck|expect-error|ignore)|vitest-environment|jest-environment|jsx\w*|license|preserve)\b|[#!]\s*__(?:PURE|NO_SIDE_EFFECTS)__|\/\s*<(?:reference|amd-module|amd-dependency)\b)/u;
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

function hasDetectSecretsPragma(comment: TSESTree.Comment, text: string): boolean {
  if (!comment.value.includes("pragma:")) return false;
  let lineStart = Math.max(text.lastIndexOf("\r", comment.range[0] - 1), text.lastIndexOf("\n", comment.range[0] - 1)) + 1;
  while (lineStart < comment.range[1]) {
    const nextCr = text.indexOf("\r", lineStart);
    const nextLf = text.indexOf("\n", lineStart);
    const lineEnd = Math.min(nextCr < 0 ? text.length : nextCr, nextLf < 0 ? text.length : nextLf);
    if (hasPragmaInReaderLine(comment, text.slice(lineStart, lineEnd), lineStart)) return true;
    lineStart = lineEnd + (text[lineEnd] === "\r" && text[lineEnd + 1] === "\n" ? 2 : 1);
  }
  return false;
}

function hasPragmaInReaderLine(comment: TSESTree.Comment, rawLine: string, lineStart: number): boolean {
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

export default createRule<[], "testComment">({
  name: "no-test-comments",
  documentation: NO_TEST_COMMENTS_DOCUMENTATION,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: NO_TEST_COMMENTS_DOCUMENTATION.summary },
    schema: [],
    messages: { testComment: "Express this explanation in the test name, fixture or assertion, then remove the comment." },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context) || isGeneratedFile(context, context.sourceCode.text)) return {};
    const filename = scopedFilename(context);
    const unambiguous = /(?:^|\/)(?:tests?|__tests__|fixtures|__fixtures__|__mocks__)\//u.test(filename) || /\.(?:test|spec|e2e|integration)\.[cm]?[jt]sx?$/u.test(filename);
    const framework = context.sourceCode.ast.body.some(statement => statement.type === AST_NODE_TYPES.ImportDeclaration && statement.importKind !== "type" &&
      (statement.specifiers.length === 0 || statement.specifiers.some(specifier => specifier.type !== AST_NODE_TYPES.ImportSpecifier || specifier.importKind !== "type")) &&
      ["vitest", "@jest/globals", "@playwright/test", "bun:test", "node:test"].includes(statement.source.value));
    if (!unambiguous && !framework) return {};
    return {
      Program(): void {
        const comments = context.sourceCode.getAllComments();
        const legalLines = new Set<number>();
        for (const [index, comment] of comments.entries()) {
          if (comment.type !== "Line" || !LEGAL.test(comment.value)) continue;
          legalLines.add(index);
          for (const direction of [-1, 1]) {
            let previous = comment;
            for (let next = index + direction; next >= 0 && next < comments.length; next += direction) {
              const neighbor = comments[next];
              if (neighbor?.type !== "Line" || Math.abs(neighbor.loc.start.line - previous.loc.start.line) !== 1) break;
              legalLines.add(next);
              previous = neighbor;
            }
          }
        }
        for (const [index, comment] of comments.entries()) {
          const body = comment.value.trim().replace(/^\*\s*/u, "");
          if (DIRECTIVE.test(body) || LEGAL.test(comment.value) || legalLines.has(index) || TYPE_CONTRACT.test(comment.value) || hasDetectSecretsPragma(comment, context.sourceCode.text)) continue;
          context.report({
            node: comment,
            messageId: "testComment",
            fix: fixer => {
              const text = context.sourceCode.text;
              const own = ownLineCommentRemovalRange(text, comment);
              if (own !== null) return fixer.replaceTextRange(own.range, commentLineEndings(text, own));
              const trailing = trailingCommentRemovalRange(text, comment);
              if (trailing !== null) return fixer.replaceTextRange(trailing.range, "");
              const endings = context.sourceCode.getText(comment).replace(/[^\r\n\u2028\u2029]/gu, "");
              if (endings.length > 0) {
                let start = comment.range[0];
                while (start > 0 && /[\t ]/u.test(text[start - 1] ?? "")) start--;
                return fixer.replaceTextRange([start, comment.range[1]], endings);
              }
              const before = text[comment.range[0] - 1] ?? "";
              const after = text[comment.range[1]] ?? "";
              const separator = before.length > 0 && after.length > 0 && !/\s/u.test(before + after) ? " " : "";
              return fixer.replaceText(comment, separator);
            },
          });
        }
      },
    };
  },
});
