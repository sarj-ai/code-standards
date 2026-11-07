/** @fileoverview prefer-zod-enum-validator — the documentation and executable examples of `@sarj/prefer-zod-enum-validator`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_ZOD_ENUM_VALIDATOR_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Express closed string validators with a reusable Zod enum schema.",
  rationale: "Handwritten membership branches and parallel literal types repeat the accepted values and can drift. A named enum schema supplies validation and its inferred TypeScript union.",
  remediation: "Declare a module-level Schema = z.enum([…]), derive its type with z.infer<typeof Schema>, and use Schema.parse(value) or Schema.safeParse(value).success. Preserve any intentional error, fallback, or protocol behavior when migrating.",
  category: "maintainability",
  autofix: "none",
  requiresTypeInformation: false,
  references: ["https://zod.dev/api#enums", "https://zod.dev/basics#inferring-types"],
  limitations: [
    "Inspects synchronous single-parameter functions explicitly accepting unknown or string, whose complete body is a strict string-equality disjunction, an equivalent reject conjunction, or a closed switch that returns the input and throws otherwise. Boolean membership functions are also inspected.",
    "At least two distinct static string values are required. Membership collections, additional guards, coercion, normalization, transformed returns, methods, contextual parameter types, and multi-parameter functions are outside this bounded detector.",
    "Migration is manual because Zod errors, initialization and constructor hooks are observable; retain intentional failure behavior. A predicate must not be replaced with a throwing parse call. Test and generated files are excluded.",
  ],
  examples: [
    { id: "schema-validator", title: "Define validation and the type from one enum", outcome: "no-match", files: [{ path: "src/status.ts", source: "import { z } from 'zod'; const StatusSchema = z.enum(['ran', 'failed']); type Status = z.infer<typeof StatusSchema>; function status(value: unknown): Status { return StatusSchema.parse(value); }" }], focusPath: "src/status.ts", expectedCount: 0, public: true },
    { id: "manual-validator", title: "Replace a closed handwritten string parser", outcome: "match", files: [{ path: "src/status.ts", source: "type Status = 'ran' | 'failed'; function status(value: unknown): Status { if (value === 'ran' || value === 'failed') return value; throw new Error('Invalid status'); }" }], focusPath: "src/status.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
