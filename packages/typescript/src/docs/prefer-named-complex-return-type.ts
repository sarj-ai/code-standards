/** @fileoverview prefer-named-complex-return-type — the documentation and executable examples of `@sarj/prefer-named-complex-return-type`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_NAMED_COMPLEX_RETURN_TYPE_DOCUMENTATION = {
  defaultLevel: "error",
  summary:
    "Prefer a named contract for structurally complex function return types.",
  rationale:
    "A large inline return annotation hides a reusable domain concept and makes signatures difficult to scan.",
  remediation:
    "Name the complex nested shape while preserving its generic wrappers and type parameters; reference the named contract from the return annotation.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Automatic fixes only reuse one existing exported nongeneric alias with exactly matching context-free type tokens for an unused private function declaration. Shared/public functions, missing or ambiguous aliases and locally dependent types remain manual.",
    "Only explicit object types with at least three members and unions with at least three object variants are reported.",
    "Any single-argument generic wrapper is traversed to find nested shapes, not assumed semantically transparent. Inferred return types are outside this rule; extraction is manual and must preserve locally bound type parameters with generic named contracts. Types depending on polymorphic this or a local value query are excluded.",
  ],
  examples: [
    {
      id: "named-result",
      title: "Name a multi-state result",
      outcome: "no-match",
      files: [
        {
          path: "src/queue.ts",
          source:
            "type ClaimResult = { state: 'idle' } | { state: 'waiting'; retryAt: number } | { state: 'claimed'; id: string }; export function claim(): ClaimResult { return { state: 'idle' }; }",
        },
      ],
      focusPath: "src/queue.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "inline-result",
      title: "Do not inline a multi-state result",
      outcome: "match",
      files: [
        {
          path: "src/queue.ts",
          source:
            "export function claim(): { state: 'idle' } | { state: 'waiting'; retryAt: number } | { state: 'claimed'; id: string } { return { state: 'idle' }; }",
        },
      ],
      focusPath: "src/queue.ts",
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
            "export type Claim = { id: string; name: string; active: boolean }; function claim(): { id: string; name: string; active: boolean } { return { id: '', name: '', active: true }; }",
        },
      ],
      fixedFiles: [
        {
          path: "src/autofix-example.ts",
          source:
            "export type Claim = { id: string; name: string; active: boolean }; function claim(): Claim { return { id: '', name: '', active: true }; }",
        },
      ],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
