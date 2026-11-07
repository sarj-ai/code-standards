/** @fileoverview no-string-concat-in-loop — the documentation and executable examples of `@sarj/no-string-concat-in-loop`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_STRING_CONCAT_IN_LOOP_DOCUMENTATION = {
  summary:
    "Prefer collecting string fragments over repeatedly accumulating a growing string inside a loop.",
  rationale:
    "Repeatedly rebuilding a growing string can copy all prior content on each iteration, making total work grow quadratically.",
  remediation:
    "Consider collecting fragments and joining once; preserve intermediate observations and coercion timing, and measure hot paths.",
  category: "performance",
  autofix: "safe",
  limitations: [
    "Automatic fixes require a sole exported zero-argument function with exactly a literal string initializer, a two-or-more literal-string for-of accumulation, and return of that same local string. Comments, intermediate reads, callbacks, imports, coercion and other control flow remain manual.",
    "Only local identifiers initialized with a string or template literal and accumulated in a loop body are inspected.",
    "Deferred function bodies are excluded except recognized direct forEach callbacks. Syntax does not establish engine-specific string allocation complexity.",
  ],
  examples: [
    {
      id: "join-fragments",
      title: "Join collected fragments after the loop",
      outcome: "no-match",
      files: [
        {
          path: "src/render.ts",
          source:
            'const parts = []; for (const item of items) { parts.push(item); } const output = parts.join("");',
        },
      ],
      focusPath: "src/render.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "rebuild-string",
      title: "Do not rebuild a growing string in a loop",
      outcome: "match",
      files: [
        {
          path: "src/render.ts",
          source:
            "let output = ''; for (const item of items) { output = `${output}${item}`; }",
        },
      ],
      focusPath: "src/render.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven source-owned correction",
      outcome: "match",
      files: [
        {
          path: "src/autofix-example.ts",
          source:
            "export function render() { let output = ''; for (const item of ['a', 'b']) { output += item; } return output; }",
        },
      ],
      fixedFiles: [
        {
          path: "src/autofix-example.ts",
          source:
            "export function render() { const output = ['', 'a', 'b'].join(\"\"); return output; }",
        },
      ],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
