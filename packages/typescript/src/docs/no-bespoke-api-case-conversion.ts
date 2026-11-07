/** @fileoverview no-bespoke-api-case-conversion — the documentation and executable examples of `@sarj/no-bespoke-api-case-conversion`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_BESPOKE_API_CASE_CONVERSION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary:
    "Review direct snake_case/camelCase mirror mappings on explicitly API-typed adapter values.",
  rationale:
    "Duplicating wire-name translation can drift from an API client contract. When the SDK owns application-facing names, centralizing conversion avoids maintaining another mirror by hand.",
  remediation:
    "Move wire-name ownership and case conversion into the generated SDK/model layer; keep application adapters on the generated typed surface.",
  category: "architecture",
  autofix: "none",
  limitations: [
    "Only adapter/adapters files and receivers explicitly annotated with a scope-resolved type imported from an API/client/SDK/contract/generated module are checked. Unrelated imports, local type shadows, reassigned receivers and inferred receiver types are excluded.",
    "Only object properties that directly translate the same identifier between snake_case and lowerCamelCase are reported.",
    "Quoted/computed protocol keys, generated/vendor code, tests, fixtures, and indirect conversions are intentionally excluded.",
  ],
  examples: [
    {
      id: "generated-client-surface",
      title: "Use the generated client's application-facing property names",
      outcome: "no-match",
      files: [
        {
          path: "src/user-adapter.ts",
          source:
            "import type { User } from './generated-client';\nexport const toUser = (raw: User) => ({ displayName: raw.displayName });",
        },
      ],
      focusPath: "src/user-adapter.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "bespoke-wire-case-conversion",
      title: "Do not reproduce SDK case conversion in an application adapter",
      outcome: "match",
      files: [
        {
          path: "src/user-adapter.ts",
          source:
            "import type { User } from './api-contract';\nexport const toUser = (raw: User) => ({ displayName: raw.display_name });",
        },
      ],
      focusPath: "src/user-adapter.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
