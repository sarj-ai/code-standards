/**
 * @fileoverview no-frontend-comments — express frontend behavior through executable code.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-frontend-comments.test.ts
 */

import type { TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { isFrontendSource } from "./_is-frontend-source.js";
import { ownsTestComments } from "./no-test-comments.js";

type MessageIds = "noFrontendComments";
type Options = readonly [{ readonly allFiles?: boolean }];

interface SourceRange {
  readonly start: number;
  readonly end: number;
}

export const NO_FRONTEND_COMMENTS_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Express frontend behavior through code instead of prose comments.",
  rationale: "Frontend comments can drift from executable behavior and conceal names, types or structure that should communicate the same information.",
  remediation: "Use clear names, types, helpers and assertions, then remove the comment. Move tool settings into their owning configuration where supported. Whitespace-only single-line comments can be replaced with a space; review all other comments and their contracts manually.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Reports every actual line, block, JSDoc and JSX comment in maintained frontend source, including legal notices and executable directives. The existing no-test-comments rule owns maintained test files and applies the same blanket frontend ban, avoiding duplicate diagnostics between these two rules. Strings, template data, rendered JSX text and generated/vendor sources are excluded.",
    "Frontend scope is established by JSX-capable extensions, use client/use server directives, framework imports, or the nearest package manifest declaring a frontend framework dependency. Pure helpers in those packages are included. Set allFiles: true on both this rule and no-test-comments in a frontend ESLint override for dependency-free or unsupported frameworks; file names alone do not infer application ownership.",
    "This is a blanket policy warning, including comments preserved by narrower comment-hygiene rules. Behavioral annotations, JavaScript type comments, required legal notices and tool directives require manual migration or an explicit policy exception; the rule never automatically deletes them.",
    "Automatic fixes replace only whitespace-only line or block comment tokens containing no line terminators with one separating space. Every existing line terminator is preserved. Comments overlapping JSX regions, multiline comments, nonempty comments and comments owned by the test rule remain manual.",
  ],
  examples: [
    { id: "frontend-prose", title: "Express view behavior in code", outcome: "match", files: [{ path: "src/view.tsx", source: "// Show current status\nexport const View = () => <p>Ready</p>;" }], focusPath: "src/view.tsx", expectedCount: 1, public: true },
    { id: "named-view", title: "The view expresses its behavior", outcome: "no-match", files: [{ path: "src/view.tsx", source: "export const View = () => <p>Ready</p>;" }], focusPath: "src/view.tsx", expectedCount: 0, public: true },
    { id: "package-helper", scenarioId: "package", title: "A plain helper belongs to its frontend package", outcome: "match", files: [{ path: "package.json", source: "{\"private\":true,\"dependencies\":{\"react\":\"19.2.0\"}}" }, { path: "src/helper.ts", source: "// Frontend helper\nexport const ready = true;" }], focusPath: "src/helper.ts", expectedCount: 1, public: true },
    { id: "package-helper-code", scenarioId: "package", title: "The helper expresses its behavior in code", outcome: "no-match", files: [{ path: "package.json", source: "{\"private\":true,\"dependencies\":{\"react\":\"19.2.0\"}}" }, { path: "src/helper.ts", source: "export const ready = true;" }], focusPath: "src/helper.ts", expectedCount: 0, public: true },
    { id: "empty-comment-separator", scenarioId: "empty-comment", title: "Keep a separating space when removing an empty comment", outcome: "match", files: [{ path: "src/helper.tsx", source: "export function identity(value: number) { return/**/value; }" }], fixedFiles: [{ path: "src/helper.tsx", source: "export function identity(value: number) { return value; }" }], focusPath: "src/helper.tsx", expectedCount: 1, public: true },
    { id: "empty-comment-removed", scenarioId: "empty-comment", title: "Preserve the return expression without a comment", outcome: "no-match", files: [{ path: "src/helper.tsx", source: "export function identity(value: number) { return value; }" }], focusPath: "src/helper.tsx", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation<Options>;


export default createRule<Options, MessageIds>({
  name: "no-frontend-comments",
  documentation: NO_FRONTEND_COMMENTS_DOCUMENTATION,
  meta: {
    defaultOptions: [{}],
    type: "suggestion",
    fixable: "code",
    docs: { description: NO_FRONTEND_COMMENTS_DOCUMENTATION.summary },
    schema: [{ type: "object", properties: { allFiles: { description: "Check comments without requiring frontend framework ownership.", type: "boolean" } }, additionalProperties: false }],
    messages: { noFrontendComments: "Frontend comments are prohibited; express the behavior in names, types or code and review any directive or legal contract before removing it." },
  },
  create(context, [options]) {
    if (isGeneratedFile(context, context.sourceCode.text) || ownsTestComments(context)) return {};
    const jsxRanges: SourceRange[] = [];
    let ambiguousJSX = false;
    function captureJSX(node: TSESTree.JSXElement | TSESTree.JSXFragment): void {
      const range = sourceRange(node.range, context.sourceCode.text.length);
      if (range === null) { ambiguousJSX = true; return; }
      const previous = jsxRanges.at(-1);
      if (previous === undefined || range.start >= previous.end) { jsxRanges.push(range); return; }
      if (range.start < previous.start || range.end > previous.end) ambiguousJSX = true;
    }
    return {
      JSXElement: captureJSX,
      JSXFragment: captureJSX,
      "Program:exit"(): void {
        const comments = context.sourceCode.getAllComments();
        if (comments.length === 0 || !(options.allFiles === true || isFrontendSource(context))) return;
        const ranges = ambiguousJSX ? new Map<TSESTree.Comment, SourceRange>()
          : emptyCommentRanges(context.sourceCode.text, comments, jsxRanges);
        for (const comment of comments) context.report({
          node: comment,
          messageId: "noFrontendComments",
          fix(fixer) {
            const range = ranges.get(comment);
            return range === undefined ? null : fixer.replaceTextRange([range.start, range.end], " ");
          },
        });
      },
    };
  },
});

function emptyCommentRanges(
  text: string, comments: readonly TSESTree.Comment[], jsxRanges: readonly SourceRange[],
): ReadonlyMap<TSESTree.Comment, SourceRange> {
  const ranges = new Map<TSESTree.Comment, SourceRange>();
  let previousEnd = 0;
  let jsxIndex = 0;
  for (const comment of comments) {
    const range = sourceRange(comment.range, text.length);
    if (range === null || range.start < previousEnd) { ranges.clear(); return ranges; }
    previousEnd = range.end;
    let jsx = jsxRanges[jsxIndex];
    while (jsx !== undefined && jsx.end <= range.start) { jsxIndex += 1; jsx = jsxRanges[jsxIndex]; }
    if (jsx !== undefined && range.start < jsx.end && range.end > jsx.start) continue;
    const empty = emptyCommentRange(text, comment);
    if (empty !== null) ranges.set(comment, empty);
  }
  return ranges;
}

function sourceRange(range: readonly [number, number], length: number): SourceRange | null {
  const [start, end] = range;
  return Number.isInteger(start) && Number.isInteger(end) && start >= 0 && end > start && end <= length
    ? { start, end } : null;
}

function emptyCommentRange(text: string, comment: TSESTree.Comment): SourceRange | null {
  const range = sourceRange(comment.range, text.length);
  if (range === null || comment.value.trim() !== "") return null;
  const { start, end } = range;
  const raw = text.slice(start, end);
  if (/[\r\n\u2028\u2029]/u.test(raw)) return null;
  if (comment.type === "Line" && raw.startsWith("//") && raw.slice(2).trim() === "") return range;
  if (comment.type === "Block" && raw.startsWith("/*") && raw.endsWith("*/") && raw.slice(2, -2).trim() === "") return range;
  return null;
}
