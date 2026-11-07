/** @fileoverview no-fat-try-blocks — the documentation and executable examples of `@sarj/no-fat-try-blocks`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_FAT_TRY_BLOCKS_DOCUMENTATION = {
  summary: "Review try blocks exceeding the configured count of syntactically selected operations.",
  rationale:
    "A broad `try` block obscures which operation failed and encourages one catch clause to recover from unrelated errors.",
  remediation:
    "Keep only the operations that share one recovery policy inside the `try` block and move other work outside it.",
  category: "correctness",
  limitations: [
    "The default threshold is three selected top-level operations, not a proof of every possible throw. A shared recovery policy may legitimately cover several operations; generated files, catchless finally blocks, rethrows, and terminal error boundaries are excluded.",
  ],
  examples: [
    {
      id: "focused-try-block",
      title: "Keep only operations with the same recovery policy in the try block",
      outcome: "no-match",
      files: [{
        path: "src/load.ts",
        source: "function f() { try { const a = one(); const b = two(); const c = three(); } catch (error) { handle(error); } const d = four(); finish(); }",
      }],
      focusPath: "src/load.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "broad-try-block",
      title: "Review whether four selected operations share one recovery policy",
      outcome: "match",
      files: [{
        path: "src/load.ts",
        source: "function f() { try { const a = one(); const b = two(); const c = three(); const d = four(); } catch (error) { handle(error); } finish(); }",
      }],
      focusPath: "src/load.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
