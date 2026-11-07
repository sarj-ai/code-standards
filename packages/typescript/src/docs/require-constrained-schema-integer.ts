/** @fileoverview require-constrained-schema-integer — the documentation and executable examples of `@sarj/require-constrained-schema-integer`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_CONSTRAINED_SCHEMA_INTEGER_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Declare integer and lower-bound validation for numeric limit and version schema fields.",
  rationale: "A bare number schema accepts fractions and negative limits or versions. Encoding the domain in validation makes downstream arithmetic and pagination contracts explicit.",
  remediation: "Use an integer schema with a positive lower bound for limit and a nonnegative lower bound for version, or reuse an existing named domain schema.",
  category: "correctness",
  limitations: [
    "This is the requested field policy for direct limit/version properties of runtime-imported Zod object/strictObject/looseObject schemas. Recognizes direct numeric and coerce constructors plus ordinary same-chain bounds and wrappers. Does not infer domains from arbitrary numeric variable names.",
    "Named schema aliases, imported domain schemas, unions, callbacks and transformations are excluded. Dynamic lower bounds count as an explicit reviewed constraint; generated/vendor files are excluded, and maintained tests are checked.",
    "Version zero remains valid; limits require at least one. Numeric custom sentinels require a precise named domain schema or an explained local suppression. No automatic runtime contract change is offered.",
  ],
  examples: [
    { id: "unconstrained-limit", title: "A number is broader than a limit", outcome: "match", files: [{ path: "src/options.ts", source: "import { z } from 'zod'; const OptionsSchema = z.object({ limit: z.number() });" }], focusPath: "src/options.ts", expectedCount: 1, public: true },
    { id: "constrained-fields", title: "Declare the numeric domain", outcome: "no-match", files: [{ path: "src/options.ts", source: "import { z } from 'zod'; const OptionsSchema = z.object({ limit: z.number().int().positive(), version: z.int().nonnegative() });" }], focusPath: "src/options.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
