/** @fileoverview excessive-commentary — the documentation and executable examples of `@sarj/excessive-commentary`. */

import type { RuleDocumentation } from "../documentation.js";

const DECORATED_HEADER = [
  "/**",
  " * This file is the seam between the local draft and backend models.",
  " * Everything above it uses the local application representation for each record.",
  " * Everything below it uses the separate wire representation for each record.",
  " * This module translates fields between those two representations during each request.",
  " * ++++++++",
  " * The backend models changed several times during early implementation work.",
  " * Each historical change required another edit in this local adapter module.",
  " * The write half previously assembled several records together in one operation.",
  " * It now saves each record separately through the route that owns it.",
  " * Clear contract types should express this boundary through the actual declarations.",
  " */",
  "const value = 1;",
].join("\n");

export const EXCESSIVE_COMMENTARY_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Flag long standalone implementation commentary that should be expressed by code.",
  rationale: "Narrative implementation paragraphs compete with the code and can drift independently from behavior.",
  remediation: "Delete narration and clarify names, types, or structure; retain only durable constraints and external contracts.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Only an unattached file-header JSDoc block with at least ten non-empty lines and 65 words that narrates file layout or change history is inspected.",
    "Generated files, tests, scripts, stories, licenses, typed API documentation, and comments attached to declarations are excluded.",
    "Safe fixes blank only interior plus-only decoration when removing those non-prose lines clears the existing volume finding. All prose bytes, comment markers and line endings remain; directives, licenses, examples, literal-output/prompt/credential contexts, Markdown structure and ambiguous comments remain for review.",
  ],
  examples: [
    {
      id: "adapter-narration",
      title: "Adapter paragraph narrates application behavior",
      outcome: "match",
      files: [{
        path: "src/adapter.ts",
        source: [
          "/**",
          " * This file is the seam between the draft and backend models.",
          " * Everything above it uses the local application representation.",
          " * Everything below it uses a separately mirrored wire representation.",
          " * Field names use the API shape while the draft uses another shape.",
          " * This module translates every field between those representations.",
          " * The backend models changed several times during early development.",
          " * Each historical change required another edit in this adapter file.",
          " * The write half previously assembled several resources in one payload.",
          " * It now saves those resources separately through their own routes.",
          " * Clear contract types and generated clients should express this boundary.",
          " */",
          "import type { Draft } from './draft';",
        ].join("\n"),
      }],
      focusPath: "src/adapter.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "protocol-constraint",
      title: "Concrete wire compatibility constraint remains local",
      outcome: "no-match",
      files: [{
        path: "src/adapter.ts",
        source: [
          "// Legacy clients send `execution_phase` until API-812 is retired.",
          "// Keep conversion in GeneratedClientAdapter.",
          "export const phase = raw.execution_phase;",
        ].join("\n"),
      }],
      focusPath: "src/adapter.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "safe-decoration",
      title: "Remove decorative volume while retaining the complete narrative",
      outcome: "match",
      files: [{ path: "src/adapter.ts", source: DECORATED_HEADER }],
      fixedFiles: [{ path: "src/adapter.ts", source: DECORATED_HEADER.replace("++++++++", "") }],
      focusPath: "src/adapter.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
