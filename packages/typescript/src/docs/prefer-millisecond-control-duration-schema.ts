/** @fileoverview prefer-millisecond-control-duration-schema — the documentation and executable examples of `@sarj/prefer-millisecond-control-duration-schema`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_MILLISECOND_CONTROL_DURATION_SCHEMA_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Require application-owned Zod control-duration fields to use millisecond granularity.",
  rationale:
    "Second-granularity timeout and scheduling controls lose precision and invite implicit unit conversion at API boundaries. Encoding milliseconds in the schema keeps the unit explicit and composes with platform timing APIs.",
  remediation:
    "Rename the field with an `Ms`/`_ms` suffix and express its bounds and default in milliseconds; update the owning API contract rather than converting in application code.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Only direct identifier keys with recognizable numeric Zod leaves in application-owned z.object/z.strictObject schemas are checked; aliases and transformations are not inferred.",
    "The rule covers control timings such as timeout, delay, interval, backoff, TTL, lease, heartbeat, debounce, and throttle; observed durations and business-domain periods are excluded.",
    "Quoted/computed protocol keys, generated/vendor code, tests, fixtures, and non-Zod schemas are excluded.",
  ],
  examples: [
    {
      id: "millisecond-timeout-schema",
      title: "Encode control timing in milliseconds",
      outcome: "no-match",
      files: [
        {
          path: "src/request.ts",
          source: "import { z } from 'zod';\nexport const RequestSchema = z.object({ timeoutMs: z.number().int().min(1000).max(300000).default(30000) });",
        },
      ],
      focusPath: "src/request.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "second-timeout-schema",
      title: "Do not expose second-granularity timeout controls",
      outcome: "match",
      files: [
        {
          path: "src/request.ts",
          source: "import { z } from 'zod';\nexport const RequestSchema = z.object({ timeout_seconds: z.number().int().min(1).max(300).default(30) });",
        },
      ],
      focusPath: "src/request.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
