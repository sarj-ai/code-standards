/** @fileoverview prefer-named-literal-union — documentation and executable examples. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_NAMED_LITERAL_UNION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Name repeated inline string literal unions in a module.",
  rationale: "Repeated literal unions can drift when a domain gains or loses a value.",
  remediation: "Declare the domain in one type alias and reference that alias at each use.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Without a module-level alias, reports begin at the second use of a union with at least three distinct string values or the third use of a union with two. Matching unions have the same string values and nullish members.",
    "Direct arguments to Pick, Omit, Exclude, Extract, Record, Partial, Required and Readonly are exempt. The named callback domain rule owns inline literal unions in exported callback parameters. Tests and generated files are skipped.",
    "Automatic fixes require one visible nongeneric alias and an annotation without comments. Identical literal sets can still represent unrelated domains.",
  ],
  examples: [
    {
      id: "name-repeated-domain",
      title: "Name the shared draft state",
      outcome: "match",
      files: [
        {
          path: "src/drafts.ts",
          source: "interface Draft { state: 'queued' | 'running' | 'done'; previousState: 'queued' | 'running' | 'done' }",
        },
      ],
      focusPath: "src/drafts.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "use-named-domain",
      title: "Use one state alias",
      outcome: "no-match",
      files: [
        {
          path: "src/drafts.ts",
          source: "type DraftState = 'queued' | 'running' | 'done'; interface Draft { state: DraftState; previousState: DraftState }",
        },
      ],
      focusPath: "src/drafts.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "reuse-alias",
      title: "Reuse the declared state alias",
      outcome: "match",
      files: [
        {
          path: "src/drafts.ts",
          source: "type DraftState = 'queued' | 'running' | 'done'; interface Draft { state: 'done' | 'queued' | 'running' }",
        },
      ],
      fixedFiles: [
        {
          path: "src/drafts.ts",
          source: "type DraftState = 'queued' | 'running' | 'done'; interface Draft { state: DraftState }",
        },
      ],
      focusPath: "src/drafts.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
