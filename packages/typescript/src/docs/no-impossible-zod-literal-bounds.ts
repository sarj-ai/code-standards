/** @fileoverview no-impossible-zod-literal-bounds — the documentation and executable examples of `@sarj/no-impossible-zod-literal-bounds`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_IMPOSSIBLE_ZOD_LITERAL_BOUNDS_DOCUMENTATION = {
  summary:
    "Disallow same-chain literal Zod bounds whose accepted set is mathematically empty.",
  rationale:
    "A schema with contradictory literal bounds rejects every input, turning validation into an unreachable contract that usually reflects a typo.",
  remediation:
    "Choose compatible lower and upper bounds, or remove the constraint that does not express the intended domain.",
  category: "correctness",
  limitations: [
    "Only finite numeric literals, including unary signs and erased TypeScript wrappers, in a single schema chain are compared; number().int(), int(), int32(), uint32(), strings and arrays require an admitted integer value or length.",
    "int32() and uint32() include their intrinsic ranges. The managed preset delegates explicit real-bound conflicts to upstream zod/no-conflicting-checks to avoid duplicate findings.",
    "Integer-domain comparisons abstain near the JavaScript safe-integer boundary.",
    "Chains with dynamic bounds, non-bound validators, transforms, pipes, or preprocessors are skipped.",
    "Test and generated files are excluded.",
  ],
  examples: [
    {
      id: "compatible-number-bounds",
      title: "Allow a number admitted by both bounds",
      outcome: "no-match",
      files: [
        {
          path: "src/schema.ts",
          source:
            'import { z } from "zod"; const S = z.number().gte(3).lte(3);',
        },
      ],
      focusPath: "src/schema.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "contradictory-number-bounds",
      title: "Reject an empty numeric interval",
      outcome: "match",
      files: [
        {
          path: "src/schema.ts",
          source:
            'import { z } from "zod"; const S = z.number().min(5).max(4);',
        },
      ],
      focusPath: "src/schema.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
