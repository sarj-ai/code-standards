/** @fileoverview no-restated-comment — the documentation and executable examples of `@sarj/no-restated-comment`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_RESTATED_COMMENT_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Flag short standalone comments that repeat the adjacent statement's identifiers.",
  rationale: "A comment that only repeats code adds no context and can become stale independently.",
  remediation: "Remove a genuine restatement; retain conditions, constraints, rationale, and information absent from the statement.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Only standalone line comments of two to eight words with at least two content tokens directly above a supported single-line statement are inspected; one-word headings and sentence-ending punctuation are excluded.",
    "Evidence comes from that statement's identifier tokens, not strings, template text, comments, or neighboring statements. Stopwords and inflection folding are heuristic, not proof of semantic equivalence.",
    "Directives, protected references, conditions, restrictions, ordering, repetition, direction, questions, prose paragraphs, sibling-group labels, novel content, and generated files are excluded. Automatic deletion is limited to whole-line comments whose removal preserves adjacent tool directives.",
    "The conservative sibling-group exemption includes enclosing sibling groups and declaration/type-query pairs; it can miss genuine restatements inside those groups.",
  ],
  examples: [
    { id: "reason-comment", title: "Keep a condition the statement does not establish", outcome: "no-match", files: [{ path: "src/cache.ts", source: "// Serialize key only after validation.\nconst key = serialize(input);" }], focusPath: "src/cache.ts", expectedCount: 0, public: true },
    { id: "restated-comment", title: "Remove a comment that repeats the statement", outcome: "match", files: [{ path: "src/cache.ts", source: "// Serialize key\nconst key = serialize(input);" }], focusPath: "src/cache.ts", expectedCount: 1, public: true },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "// Serialize key\nconst key = serialize(input);" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "\nconst key = serialize(input);" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
