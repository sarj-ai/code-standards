/** @fileoverview prefer-module-level-schema — the documentation and executable examples of `@sarj/prefer-module-level-schema`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_MODULE_LEVEL_SCHEMA_DOCUMENTATION = {
  summary: "Declare a Zod schema at module scope when it closes over nothing in the enclosing function",
  rationale: "A schema created inside a function is rebuilt on each call. Module scope can enable reuse across callers; local schemas already support local type inference.",
  remediation: "Move the closed schema declaration to module scope and reference it from the function.",
  category: "performance",
  limitations: ["Schemas that depend on local state or are wrapped in a recognized memoization helper are excluded.", "Eager calls outside the recognized Zod construction chain and new expressions are excluded. This is manual guidance, not a purity proof: review getters, callback effects, schema identity, error customization, and module initialization order before moving construction."],
  examples: [
    { id: "module-schema", title: "Declare the schema once", outcome: "no-match", files: [{ path: "src/handler.ts", source: "import { z } from 'zod'; const ZBody = z.object({ id: z.string(), name: z.string() }); export function handle(raw: unknown) { return ZBody.parse(raw); }" }], focusPath: "src/handler.ts", expectedCount: 0, public: true },
    { id: "local-schema", title: "Do not rebuild a closed schema", outcome: "match", files: [{ path: "src/handler.ts", source: "import { z } from 'zod'; export function handle(raw: unknown) { const ZBody = z.object({ id: z.string(), name: z.string() }); return ZBody.parse(raw); }" }], focusPath: "src/handler.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
