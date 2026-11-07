/** @fileoverview no-log-only-catch — the documentation and executable examples of `@sarj/no-log-only-catch`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_LOG_ONLY_CATCH_DOCUMENTATION = {
  summary: "Disallow `catch` clauses that only log (or silently do nothing) and then swallow the error; rethrow or handle it instead.",
  rationale: "Swallowing an exception after logging lets execution continue as if the operation succeeded.",
  remediation: "Rethrow the error, return an explicit fallback, or perform concrete recovery.",
  category: "correctness",
  limitations: ["Documented intentional ignores, tests, and catches with observable recovery are excluded."],
  examples: [
    { id: "rethrow-after-log", title: "Preserve failure after logging", outcome: "no-match", files: [{ path: "src/task.ts", source: "try { run(); } catch (error) { console.error(error); throw error; }" }], focusPath: "src/task.ts", expectedCount: 0, public: true },
    { id: "log-and-swallow", title: "Do not only log a failure", outcome: "match", files: [{ path: "src/task.ts", source: "try { run(); } catch (error) { console.error(error); }" }], focusPath: "src/task.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
