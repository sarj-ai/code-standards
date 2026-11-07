/** @fileoverview prefer-module-level-refined-schema — the documentation and executable examples of `@sarj/prefer-module-level-refined-schema`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_MODULE_LEVEL_REFINED_SCHEMA_DOCUMENTATION = {
  defaultLevel: "warning",
  summary:
    "Declare closed Zod scalar, format, and wrapper schemas at module scope.",
  rationale:
    "A closed validation pipeline created inside a function is rebuilt on every invocation and obscures a reusable constraint.",
  remediation:
    "Move the validation schema to module scope, name it with a PascalCase Schema suffix, and call parse on the shared schema.",
  category: "performance",
  limitations: [
    "Composite object/record/tuple/union schemas are owned by prefer-module-level-schema.",
    "Schemas that depend on function-local or mutable state, localized text, receiver state, lazy construction, or recognized memoization are excluded.",
    "Literal string z.enum domains are owned by prefer-shared-zod-enum.",
    "Eager calls outside recognized Zod construction chains and new expressions are excluded. This is manual guidance, not a purity proof: review getters, callback effects, error customization, schema identity, and module initialization order before moving construction.",
  ],
  examples: [
    {
      id: "module-refinement",
      title: "Share the validation schema",
      outcome: "no-match",
      files: [{
        path: "src/options.ts",
        source: "import { z } from 'zod'; const NameSchema = z.string().trim().min(1).max(128); export function parse(value: unknown) { return NameSchema.parse(value); }",
      }],
      focusPath: "src/options.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "local-refinement",
      title: "Do not rebuild a closed validation chain",
      outcome: "match",
      files: [{
        path: "src/options.ts",
        source: "import { z } from 'zod'; export function parse(value: unknown) { return z.string().trim().min(1).max(128).parse(value); }",
      }],
      focusPath: "src/options.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
