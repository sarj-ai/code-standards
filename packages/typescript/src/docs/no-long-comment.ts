/** @fileoverview no-long-comment — the documentation and executable examples of `@sarj/no-long-comment`. */

import type { RuleDocumentation } from "../documentation.js";

const DECORATED_COMMENT = [
  "/**",
  " * The reader accepts data. The reader checks format. The reader preserves ordering. The reader buffers records. The reader closes cleanly.",
  " * ++++++++",
  " * The writer accepts batches. The writer records progress. The writer flushes changes. The writer closes cleanly.",
  " */",
  "const value = 1;",
].join("\n");

export const NO_LONG_COMMENT_DOCUMENTATION = {
  summary: "Flag unusually large unstructured JSDoc blocks in implementation code.",
  rationale: "Large narrative comments become stale and obscure the local facts that belong beside the code.",
  remediation: "Keep only durable local constraints and express the remaining behavior in code.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Only JSDoc blocks are inspected; structured API docs, tests, scripts, generated files, and versioned dependencies are excluded.",
    "Safe fixes blank only interior plus-only decoration when the retained prose gains actual paragraph structure. All prose bytes, comment markers and line endings remain; directives, licenses, examples, literal-output/prompt/credential contexts, Markdown structure and ambiguous comments remain for review.",
  ],
  examples: [
    {
      id: "structured-jsdoc",
      title: "Paragraphs separate a component's durable constraints",
      outcome: "no-match",
      files: [{
        path: "src/composer.ts",
        source: [
          "/**",
          " * Shared composer.",
          " *",
          " * It serves the room. It serves task comments. It stays visually calm. It accepts attachments.",
          " *",
          " * The `tone` prop supplies task styling. The `leadingTools` prop supplies controls.",
          " * The parent owns uploads. The component owns focus.",
          " */",
          "",
          "export const Composer = forwardRef(function Composer() { return null; });",
        ].join("\n"),
      }],
      focusPath: "src/composer.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "prose-wall",
      title: "One paragraph narrates a chart's design history",
      outcome: "match",
      files: [{
        path: "src/chart.ts",
        source: `/**
 * The ports chart shows arrivals and departures across the network.
 * It was originally a line chart, but the lines crossed too often.
 * Bars make adjacent ports easier to compare at a glance.
 * The axis starts at zero so visual differences stay proportional.
 * A single series uses the site navy for brand consistency.
 * Empty ports use a neutral ink so missing traffic remains visible.
 * Tooltip values repeat the units shown on the vertical axis.
 * The chart intentionally keeps labels horizontal on wide screens.
 */
export function PortBars() { return null; }`,
      }],
      focusPath: "src/chart.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-decoration",
      title: "Remove a decorative divider while retaining both prose paragraphs",
      outcome: "match",
      files: [{ path: "src/reader.ts", source: DECORATED_COMMENT }],
      fixedFiles: [{ path: "src/reader.ts", source: DECORATED_COMMENT.replace("++++++++", "") }],
      focusPath: "src/reader.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
