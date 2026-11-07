/** @fileoverview prefer-shared-zod-enum — the documentation and executable examples of `@sarj/prefer-shared-zod-enum`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_SHARED_ZOD_ENUM_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Give repeated literal Zod enum domains one reusable module-level schema.",
  rationale: "Repeated literal domains hide a shared contract and allow equivalent fields to drift independently.",
  remediation: "Declare a module-level named Zod enum schema and reuse it at each field or contract site.",
  category: "maintainability",
  limitations: ["Only two or more exact, same-order direct z.enum calls with string-literal arrays (including no-substitution templates and erased TypeScript wrappers) and no customization argument in one module are inspected; one-off, computed, and customized domains require review. Equal values do not prove a shared business domain: retain local schemas when ownership or future evolution differs, and review initialization order before extraction."],
  examples: [
    { id: "shared-provider", title: "Reuse a named enum schema", outcome: "no-match", files: [{ path: "src/provider.ts", source: "import { z } from 'zod'; const ProviderSchema = z.enum(['agy', 'claude', 'sol']); const JobSchema = z.object({ provider: ProviderSchema }); const StatusSchema = z.object({ provider: ProviderSchema.optional() });" }], focusPath: "src/provider.ts", expectedCount: 0, public: true },
    { id: "inline-provider", title: "Do not repeat an inline enum domain", outcome: "match", files: [{ path: "src/provider.ts", source: "import { z } from 'zod'; const JobSchema = z.object({ provider: z.enum(['agy', 'claude', 'sol']) }); const StatusSchema = z.object({ provider: z.enum(['agy', 'claude', 'sol']).optional() });" }], focusPath: "src/provider.ts", expectedCount: 2, public: true },
  ],
} as const satisfies RuleDocumentation;
