/** @fileoverview prefer-zod-field-bounds — documentation and executable examples for `@sarj/prefer-zod-field-bounds`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_ZOD_FIELD_BOUNDS_DOCUMENTATION = {
  defaultLevel: "warning",
  summary:
    "Declare a pure integer field range on its Zod field schema instead of an object refinement.",
  rationale:
    "An object-level refinement can hide one field's domain range from generated JSON Schema. A native field bound states the range beside the integer contract without a custom predicate.",
  remediation:
    "Consider the equivalent min/gte/gt/max/lte/lt field constraint. Review error paths, issue codes and validation order before replacing the refinement; no automatic fix is offered.",
  category: "correctness",
  limitations: [
    "Warning-only advice for direct runtime imports from full Zod (zod or zod/v4), a direct object shape, one zero-option number().int() target, and one synchronous arrow comparison with a safe integer literal. Import aliases and pure primitive siblings are supported. This is a maintainability preference, not proof of a functional defect.",
    "Cross-field, fractional, scalar, block-body, dynamic, async and contextual validators remain allowed. Defaults, transforms, brands, custom errors, opaque fields, spreading, computed keys, later wrappers and opaque enclosing calls are excluded. Existing field bounds are excluded rather than reinterpreted.",
    "Delegates limit/version fields unconditionally to require-constrained-schema-integer, using that owner's shared policy. Oxlint does not expose other enabled rules; selecting only this rule still leaves those fields to their owner.",
    "Visible import mutation or escaping a namespace prevents inference; external monkeypatches and custom module resolution are not inferred. Generated files are excluded; maintained tests are checked. Mini and older Zod APIs are excluded. No autofix preserves object-level error paths automatically.",
  ],
  examples: [
    {
      id: "object-integer-range",
      title: "A pure field range hidden in an object validator",
      outcome: "match",
      files: [
        {
          path: "src/count.ts",
          source:
            "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1);",
        },
      ],
      focusPath: "src/count.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "native-field-range",
      title: "Keep the integer domain on its field",
      outcome: "no-match",
      files: [
        {
          path: "src/count.ts",
          source:
            "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int().min(1) });",
        },
      ],
      focusPath: "src/count.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
