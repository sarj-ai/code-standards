/** @fileoverview require-pascal-case-zod-schema-name — the documentation and executable examples of `@sarj/require-pascal-case-zod-schema-name`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_PASCAL_CASE_ZOD_SCHEMA_NAME_DOCUMENTATION = {
  summary: "Require confirmed module-level Zod schema contracts to use PascalCase with a `Schema` suffix.",
  rationale: "A reusable Zod schema is a runtime type contract. PascalCase mirrors that role; SCREAMING_SNAKE_CASE should remain reserved for scalar values and lookup tables.",
  remediation: "Rename the binding to PascalCase ending in `Schema` (for example, `MutationRouteBaseSchema`).",
  category: "style",
  aliases: ["zod-naming-convention"],
  autofix: "safe",
  limitations: [
    "Only module-level bindings proven from a Zod import or a same-file proven schema are checked.",
    "Tests, benchmarks, generated files, imported schemas, re-export aliases, and arbitrary wrapper-factory results are excluded.",
    "Automatic renaming is limited to private module const bindings with no collisions, exports, dynamic eval, or inferred function names. Public names and unsafe reference shapes remain manual.",
  ],
  examples: [
    { id: "runtime-type-schema-name", title: "Name a reusable schema like a runtime type contract", outcome: "no-match", files: [{ path: "src/user.ts", source: "import { z } from 'zod';\nexport const UserSchema = z.object({ id: z.string() });" }], focusPath: "src/user.ts", expectedCount: 0, public: true },
    { id: "screaming-schema-name", title: "Do not name a schema like a scalar constant", outcome: "match", files: [{ path: "src/user.ts", source: "import { z } from 'zod';\nexport const USER_SCHEMA = z.object({ id: z.string() });" }], focusPath: "src/user.ts", expectedCount: 1, public: true },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "import { z } from \"zod\"; const USER_SCHEMA = z.string();" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "import { z } from \"zod\"; const UserSchema = z.string();" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
