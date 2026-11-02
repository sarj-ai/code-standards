/**
 * @fileoverview no-frontend-comments — express frontend behavior through executable code.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-frontend-comments.test.ts
 */

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { isFrontendSource } from "./_is-frontend-source.js";
import { ownsTestComments } from "./no-test-comments.js";

type MessageIds = "noFrontendComments";
type Options = readonly [{ readonly allFiles?: boolean }];

export const NO_FRONTEND_COMMENTS_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Express frontend behavior through code instead of prose comments.",
  rationale: "Frontend comments can drift from executable behavior and conceal names, types or structure that should communicate the same information.",
  remediation: "Use clear names, types, helpers and assertions, then remove the comment. Move tool settings into their owning configuration where supported. Review behavioral directives and legal notices before editing; no automatic deletion changes those contracts.",
  category: "maintainability",
  autofix: "none",
  limitations: [
    "Reports every actual line, block, JSDoc and JSX comment in maintained frontend source, including legal notices and executable directives. The existing no-test-comments rule owns maintained test files and applies the same blanket frontend ban, avoiding duplicate diagnostics between these two rules. Strings, template data, rendered JSX text and generated/vendor sources are excluded.",
    "Frontend scope is established by JSX-capable extensions, use client/use server directives, framework imports, or the nearest package manifest declaring a frontend framework dependency. Pure helpers in those packages are included. Set allFiles: true on both this rule and no-test-comments in a frontend ESLint override for dependency-free or unsupported frameworks; file names alone do not infer application ownership.",
    "This is a blanket policy warning, including comments preserved by narrower comment-hygiene rules. Behavioral annotations, JavaScript type comments, required legal notices and tool directives require manual migration or an explicit policy exception; the rule never automatically deletes them.",
  ],
  examples: [
    { id: "frontend-prose", title: "Express view behavior in code", outcome: "match", files: [{ path: "src/view.tsx", source: "// Show current status\nexport const View = () => <p>Ready</p>;" }], focusPath: "src/view.tsx", expectedCount: 1, public: true },
    { id: "named-view", title: "The view expresses its behavior", outcome: "no-match", files: [{ path: "src/view.tsx", source: "export const View = () => <p>Ready</p>;" }], focusPath: "src/view.tsx", expectedCount: 0, public: true },
    { id: "package-helper", scenarioId: "package", title: "A plain helper belongs to its frontend package", outcome: "match", files: [{ path: "package.json", source: "{\"private\":true,\"dependencies\":{\"react\":\"19.2.0\"}}" }, { path: "src/helper.ts", source: "// Frontend helper\nexport const ready = true;" }], focusPath: "src/helper.ts", expectedCount: 1, public: true },
    { id: "package-helper-code", scenarioId: "package", title: "The helper expresses its behavior in code", outcome: "no-match", files: [{ path: "package.json", source: "{\"private\":true,\"dependencies\":{\"react\":\"19.2.0\"}}" }, { path: "src/helper.ts", source: "export const ready = true;" }], focusPath: "src/helper.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation<Options>;


export default createRule<Options, MessageIds>({
  name: "no-frontend-comments",
  documentation: NO_FRONTEND_COMMENTS_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_FRONTEND_COMMENTS_DOCUMENTATION.summary },
    schema: [{ type: "object", properties: { allFiles: { type: "boolean" } }, additionalProperties: false }],
    messages: { noFrontendComments: "Frontend comments are prohibited; express the behavior in names, types or code and review any directive or legal contract before removing it." },
  },
  defaultOptions: [{}],
  create(context, [options]) {
    if (isGeneratedFile(context, context.sourceCode.text) || ownsTestComments(context)) return {};
    return {
      Program(): void {
        const comments = context.sourceCode.getAllComments();
        if (comments.length === 0 || !(options.allFiles === true || isFrontendSource(context))) return;
        for (const comment of comments) context.report({ node: comment, messageId: "noFrontendComments" });
      },
    };
  },
});
