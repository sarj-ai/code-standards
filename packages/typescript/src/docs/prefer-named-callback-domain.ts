/** @fileoverview prefer-named-callback-domain — the documentation and executable examples of `@sarj/prefer-named-callback-domain`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_NAMED_CALLBACK_DOMAIN_DOCUMENTATION = {
  summary:
    "Name literal-union domains used by callbacks in exported contracts.",
  rationale:
    "An inline callback domain hides a reusable vocabulary at the point where callers and implementations must agree.",
  remediation:
    "Extract the literal union to a named type and use that type in the callback parameter.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Only callback types nested in an exported type alias or exported interface are reported.",
    "Automatic fixes only reuse one existing exported nongeneric alias with exactly matching primitive literal-union tokens and the same lexical binding. Missing, ambiguous, shadowed or commented aliases remain manual.",
  ],
  examples: [
    {
      id: "named-domain",
      title: "Name the callback domain",
      outcome: "no-match",
      files: [
        {
          path: "src/options.ts",
          source:
            "export type Boundary = 'seeded' | 'queued'; export interface Options { done?: (boundary: Boundary) => void; }",
        },
      ],
      focusPath: "src/options.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "inline-domain",
      title: "Do not inline a public callback domain",
      outcome: "match",
      files: [
        {
          path: "src/options.ts",
          source:
            "export interface Options { done?: (boundary: 'seeded' | 'queued') => void; }",
        },
      ],
      focusPath: "src/options.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Reuse the existing authored domain alias",
      outcome: "match",
      files: [
        {
          path: "src/autofix-example.ts",
          source:
            "export type Boundary = 'seeded' | 'queued'; export interface Options { done?: (boundary: 'seeded' | 'queued') => void; }",
        },
      ],
      fixedFiles: [
        {
          path: "src/autofix-example.ts",
          source:
            "export type Boundary = 'seeded' | 'queued'; export interface Options { done?: (boundary: Boundary) => void; }",
        },
      ],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
