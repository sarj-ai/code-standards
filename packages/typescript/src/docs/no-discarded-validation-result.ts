/** @fileoverview no-discarded-validation-result — the documentation and executable examples of `@sarj/no-discarded-validation-result`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_DISCARDED_VALIDATION_RESULT_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Consume Zod validation outcomes and transformed outputs instead of discarding them.",
  rationale: "Ignoring safeParse loses failure information; ignoring a transformed parse result leaves callers using values without the declared defaults, coercions or normalization.",
  remediation: "Capture or return the parsed output. Branch on safeParse success and use data. Plain throwing validation without output changes remains supported.",
  category: "correctness",
  limitations: [
    "Checks expression-statement parse/parseAsync/safeParse/safeParseAsync calls on import-proven Zod factories and immutable local schema aliases. Await wrappers are supported.",
    "Throwing parse is reported only for source-visible output-changing schema operations. Plain validation-only parse, imported schemas, custom validators, mutable bindings, generated files and opaque effects are excluded. No automatic variable or control flow is invented.",
  ],
  examples: [
    { id: "lost-transform", title: "The normalized output is discarded", outcome: "match", files: [{ path: "app.ts", source: "import { z } from 'zod'; z.string().trim().parse(raw);" }], focusPath: "app.ts", expectedCount: 1, public: true },
    { id: "used-transform", title: "Return the parsed value", outcome: "no-match", files: [{ path: "app.ts", source: "import { z } from 'zod'; function parse(raw: unknown) { return z.string().trim().parse(raw); }" }], focusPath: "app.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
