/** @fileoverview no-frontend-comments — the documentation and executable examples of `@sarj/no-frontend-comments`. */

import type { RuleDocumentation } from "../documentation.js";

export type Options = readonly [{ readonly allFiles?: boolean }];

export const NO_FRONTEND_COMMENTS_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Express frontend behavior through code instead of prose comments.",
  rationale: "Frontend comments can drift from executable behavior and conceal names, types or structure that should communicate the same information.",
  remediation: "Use clear names, types, helpers and assertions, then remove the comment. Move tool settings into their owning configuration where supported. Whitespace-only single-line comments can be replaced with a space; review all other comments and their contracts manually.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Reports every actual line, block, JSDoc and JSX comment in maintained frontend source, including legal notices and executable directives. The existing no-test-comments rule owns maintained test files and applies the same blanket frontend ban, avoiding duplicate diagnostics between these two rules. Strings, template data, rendered JSX text and generated/vendor sources are excluded.",
    "Frontend scope is established by JSX-capable extensions, use client/use server directives, framework imports, or the nearest package manifest declaring a frontend framework dependency. Pure helpers in those packages are included. Set allFiles: true on both this rule and no-test-comments in a frontend Oxlint override for dependency-free or unsupported frameworks; file names alone do not infer application ownership.",
    "This is a blanket frontend policy, including comments preserved by narrower comment-hygiene rules. Behavioral annotations, JavaScript type comments, required legal notices and tool directives require manual migration or an explicit policy exception; the rule never automatically deletes them.",
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
