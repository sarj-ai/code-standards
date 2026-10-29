/**
 * @fileoverview no-test-comments — Express test behavior through names, fixtures and assertions instead of prose comments.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-test-comments.test.ts
 */

import { AST_NODE_TYPES } from "@typescript-eslint/utils";

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
    "Legal notices, shebangs, TypeScript triple-slash references, coverage/build annotations and explicit lint/type/test/formatter directives remain allowed. Ordinary prose embedded in a directive remains the owning tool's responsibility.",
    "The automatic fix removes comments and adjacent padding while retaining every line ending and necessary token boundary; it does not rename tests or remove executable statements. Ambiguous hyphen/underscore test basenames require a runtime testing-framework import; ordinary rule implementations ending in -test are preserved.",
  ],
  examples: [
    { id: "narrated-assertion", title: "Put behavior in the test name", outcome: "match", files: [{ path: "src/request.test.ts", source: "expect(result.status).toBe(409); // Confirm the rejected request\n" }], fixedFiles: [{ path: "src/request.test.ts", source: "expect(result.status).toBe(409);\n" }], focusPath: "src/request.test.ts", expectedCount: 1, public: true },
    { id: "named-behavior", title: "The assertion expresses the behavior", outcome: "no-match", files: [{ path: "src/request.test.ts", source: "expect(result.status).toBe(409);" }], focusPath: "src/request.test.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

const DIRECTIVE = /^(?:eslint(?:-\S+)?\b|(?:biome|oxlint|jshint|jslint|c8|v8|istanbul|vitest|prettier|dprint)\b|@(?:ts-(?:check|nocheck|expect-error|ignore)|vitest-environment|jest-environment|jsx\w*|license|preserve)\b|[#!]\s*__(?:PURE|NO_SIDE_EFFECTS)__|\/\s*<(?:reference|amd-module|amd-dependency)\b)/u;
const LEGAL = /(?:^|\n)\s*\*?\s*(?:Copyright\b|SPDX-License-Identifier:|Licensed under\b|@license\b|@preserve\b)/iu;
const TYPE_CONTRACT = /@(?:type|typedef|template|param|returns?|satisfies|callback|overload|implements|extends|augments|enum|this|import)\b/u;

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
    const unambiguous = /(?:^|\/)(?:tests?|__tests__|fixtures|__fixtures__|__mocks__|integration|e2e)\//u.test(filename) || /\.(?:test|spec|e2e|integration)\.[cm]?[jt]sx?$/u.test(filename);
    const framework = context.sourceCode.ast.body.some(statement => statement.type === AST_NODE_TYPES.ImportDeclaration && statement.importKind !== "type" &&
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
          if (DIRECTIVE.test(body) || LEGAL.test(comment.value) || legalLines.has(index) || TYPE_CONTRACT.test(comment.value)) continue;
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
