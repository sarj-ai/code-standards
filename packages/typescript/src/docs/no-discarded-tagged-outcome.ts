/** @fileoverview no-discarded-tagged-outcome — authored documentation and executable examples. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_DISCARDED_TAGGED_OUTCOME_DOCUMENTATION = {
  "defaultLevel": "warning",
  "summary": "Consume a closed tagged success or failure outcome instead of discarding it.",
  "rationale": "A returned failure channel cannot protect a caller that discards the whole outcome; awaiting a promise alone does not inspect its result.",
  "remediation": "Capture or return the outcome and handle its declared failure variant. Keep ordinary side-effect calls and throwing APIs unchanged.",
  "category": "correctness",
  "limitations": [
    "Files with direct eval or Function references abstain because source-visible static bindings cannot establish their runtime return contracts.",
    "Checks discarded calls to source-visible functions with explicit closed two-record outcome return contracts, following bounded local aliases and interfaces. Boolean ok/success tags and conventional success/error, success/failure, accepted/rejected string pairs are recognized.",
    "Awaited Promise outcomes are checked; unawaited promises retain their existing floating-promise owner. Imported functions, unresolved or inferred return types, overloaded functions, arbitrary tagged data, open unions and dynamic method calls abstain. No control flow or variable is synthesized."
  ],
  "examples": [
    {
      "id": "declared-contract",
      "title": "Preserve the declared boundary",
      "outcome": "no-match",
      "files": [
        {
          "path": "app.ts",
          "source": "type Outcome = { ok: true; value: string } | { ok: false; error: string }; function save(): Outcome { return { ok: true, value: 'saved' }; } const result = save(); if (!result.ok) report(result.error);"
        }
      ],
      "focusPath": "app.ts",
      "expectedCount": 0,
      "public": true
    },
    {
      "id": "demonstrated-gap",
      "title": "Detect the demonstrated gap",
      "outcome": "match",
      "files": [
        {
          "path": "app.ts",
          "source": "type Outcome = { ok: true; value: string } | { ok: false; error: string }; function save(): Outcome { return { ok: true, value: 'saved' }; } save();"
        }
      ],
      "focusPath": "app.ts",
      "expectedCount": 1,
      "public": true
    }
  ]
} as const satisfies RuleDocumentation;
