/** @fileoverview prefer-zod-infer — the documentation and executable examples of `@sarj/prefer-zod-infer`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_ZOD_INFER_DOCUMENTATION = {
  summary: "Derive a type from its Zod schema with `z.infer` instead of hand-writing a twin declaration beside it.",
  rationale: "A derived type stays synchronized when the runtime schema changes.",
  remediation: "Replace the hand-written twin with `z.infer<typeof Schema>`.",
  category: "correctness",
  autofix: "safe",
  limitations: [
    "Automatic fixes use the original imported Zod namespace and existing schema only for an unused private unmerged interface or object alias with a positively identical shape and no declaration-file ownership or comments. Referenced/public contracts and coarse optional matching remain manual.",
    "Only module-level const schemas and module-level type declarations are paired; local declarations are excluded rather than matched by spelling across scopes.",
    "By default every field must positively agree; collection, nested-object and referenced-schema equivalence is not inferred from outer syntax alone.",
    "This is a bounded syntactic comparison, not general type equivalence. Review schema input versus output, interface augmentation, and separately evolving domain contracts before replacing a declaration.",
    "A module-level string-union alias is also inspected beside a same-named direct enum schema only when every literal agrees and its const binding has no explicit type annotation. Enum alias migrations remain manual; dynamic, widened, transformed, constrained and independently named contracts are excluded.",
  ],
  examples: [
    { id: "inferred-type", title: "Infer the schema type", outcome: "no-match", files: [{ path: "src/user.ts", source: 'import { z } from "zod"; const UserSchema = z.object({ id: z.string() }); type User = z.infer<typeof UserSchema>;' }], focusPath: "src/user.ts", expectedCount: 0, public: true },
    { id: "handwritten-twin", title: "Do not duplicate the schema shape", outcome: "match", files: [{ path: "src/user.ts", source: 'import { z } from "zod"; const UserSchema = z.object({ id: z.string() }); interface User { id: string }' }], focusPath: "src/user.ts", expectedCount: 1, public: true },
    {
      id: "safe-autofix",
      title: "Derive an unused private twin from its existing schema",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "import { z } from \"zod\"; const UserSchema = z.object({ id: z.string() }); interface User { id: string }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "import { z } from \"zod\"; const UserSchema = z.object({ id: z.string() }); type User = z.infer<typeof UserSchema>;" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
