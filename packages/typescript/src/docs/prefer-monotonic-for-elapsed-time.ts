/** @fileoverview prefer-monotonic-for-elapsed-time — authored documentation and executable examples. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_MONOTONIC_FOR_ELAPSED_TIME_DOCUMENTATION = {
  "defaultLevel": "warning",
  "summary": "Measure elapsed time with a monotonic clock rather than wall-clock timestamps.",
  "rationale": "Clock corrections can make Date.now differences jump or turn negative even when a duration is the only intended observation.",
  "remediation": "Use performance.now consistently at both ends of a duration. Keep wall-clock timestamps when they are stored, displayed or otherwise part of the contract.",
  "category": "performance",
  "limitations": [
    "Checks private stable const Date.now captures whose every value read is the right operand of a Date.now subtraction. One advisory is emitted per clock capture, with bounded reference inspection.",
    "Absolute timestamps, escaped or exported captures, mutable bindings, dynamic clocks, shadowed Date and visible runtime mutation abstain. Clock units and the surrounding failure behavior require review; no automatic fix."
  ],
  "examples": [
    {
      "id": "declared-contract",
      "title": "Preserve the declared boundary",
      "outcome": "no-match",
      "files": [
        {
          "path": "app.ts",
          "source": "const start = performance.now(); consume(performance.now() - start);"
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
          "source": "const start = Date.now(); consume(Date.now() - start);"
        }
      ],
      "focusPath": "app.ts",
      "expectedCount": 1,
      "public": true
    }
  ]
} as const satisfies RuleDocumentation;
