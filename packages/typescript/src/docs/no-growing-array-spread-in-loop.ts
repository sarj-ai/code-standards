/** @fileoverview no-growing-array-spread-in-loop — the documentation and executable examples of `@sarj/no-growing-array-spread-in-loop`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_GROWING_ARRAY_SPREAD_IN_LOOP_DOCUMENTATION = {
  summary:
    "Review repeated prefix copies of a growing fresh local array inside a loop.",
  rationale:
    "Repeatedly copying all accumulated elements can make append collection quadratic in the output size.",
  remediation:
    "Append into a fresh locally owned output when snapshot and observation semantics permit it.",
  category: "performance",
  defaultLevel: "warning",
  requiresTypeInformation: true,
  references: [
    "https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/src/rules/no-reduce-accumulator-copy.ts",
  ],
  limitations: [
    "Initially checks a native-array for-of loop with a straight-line append-only body, a fresh local empty array outside that loop, a prefix spread followed by a definite element, and no other writes or observations across the loop.",
    "Inputs initially come from parameters, imports or declarations, optionally through plain const aliases. Locally literal-, property- and call-produced inputs are excluded while their bounds remain unproved. Retained snapshots, escaping arrays, resets, nested function references and object spreads remain outside this rule. Existing Unicorn concat-loop coverage and reducer copy analysis keep their own owners.",
    "A finding requests performance review; it is not a measured speedup claim. Corrections remain manual.",
  ],
  examples: [
    {
      id: "copy-prefix",
      title: "Repeated spread copies the accumulated rows",
      outcome: "match",
      files: [
        {
          path: "src/rows.ts",
          source:
            "export function collect(input: string[]) { let rows: string[] = []; for (const row of input) { rows = [...rows, row]; } return rows; }",
        },
      ],
      focusPath: "src/rows.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "append-rows",
      title: "Append into a fresh unobserved output",
      outcome: "no-match",
      files: [
        {
          path: "src/rows.ts",
          source:
            "export function collect(input: string[]) { const rows: string[] = []; for (const row of input) { rows.push(row); } return rows; }",
        },
      ],
      focusPath: "src/rows.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
