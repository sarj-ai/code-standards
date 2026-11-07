/** @fileoverview no-hand-rolled-sleep — the documentation and executable examples of `@sarj/no-hand-rolled-sleep`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_HAND_ROLLED_SLEEP_DOCUMENTATION = {
  summary: "Disallow uncancellable promisified timers and timeout arms.",
  rationale:
    "A timer that outlives an aborted operation or a lost promise race retains work and can keep the process alive until it fires.",
  remediation:
    "Use `node:timers/promises` with an abort signal for delays, or pass `AbortSignal.timeout(...)` to the timed operation.",
  category: "correctness",
  limitations: [
    "The rule skips tests, scripts, generated files, and client modules by default, and supports explicit path exemptions.",
    "Locally shadowed constructors/timers and value-returning timers are excluded. Only recognized browser markers are excluded; choose a runtime-compatible cancellation API for other browser modules.",
  ],
  examples: [
    {
      id: "cancellable-node-timer",
      title: "A standard-library timer accepts an abort signal",
      outcome: "no-match",
      files: [{
        path: "src/lib/queue.ts",
        source: "import { setTimeout as sleep } from \"node:timers/promises\";\nawait sleep(500, undefined, { signal });",
      }],
      focusPath: "src/lib/queue.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "uncancellable-sleep",
      title: "A Promise wraps a timer without cancellation",
      outcome: "match",
      files: [{ path: "src/lib/queue.ts", source: "await new Promise((resolve) => setTimeout(resolve, 500));" }],
      focusPath: "src/lib/queue.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
