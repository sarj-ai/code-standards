/** @fileoverview prefer-nominal-id-members — documentation and executable examples. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_NOMINAL_ID_MEMBERS_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Distinguish identifier roles sharing primitive types in object types.",
  rationale: "A property annotated with a primitive type accepts identifiers from any domain that uses that type. A swap can survive type checking even when callers pass an object with named properties.",
  remediation: "Parse identifiers with distinct branded Zod schemas at the input boundary. Use the schema output types for the corresponding properties in the domain object.",
  category: "correctness",
  limitations: [
    "Checks explicitly annotated interface properties, type literal properties and class fields. Reports the second distinct role sharing a proven string, number or homogeneous array carrier, once per object type.",
    "Uses the callable rule's role and carrier matching. Plural names require arrays. Operational identifiers, generated files, computed keys, index signatures and unproven carriers such as imported or generic types are skipped.",
    "Different names can represent the same domain, as with selectedId and storedId. Hand-typed third-party wire shapes can also legitimately use primitives until validation.",
  ],
  examples: [
    {
      id: "raw-members",
      scenarioId: "object-identifier-roles",
      title: "Primitive properties accept swapped identifiers",
      outcome: "match",
      files: [{ path: "src/receipt.ts", source: "interface Receipt { accountId: string; invoiceId: string }" }],
      focusPath: "src/receipt.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "branded-members",
      scenarioId: "object-identifier-roles",
      title: "Branded fields keep identifier roles distinct",
      outcome: "no-match",
      files: [{
        path: "src/receipt.ts",
        source: "import { z } from 'zod';\nconst AccountId = z.string().brand<'AccountId'>();\nconst InvoiceId = z.string().brand<'InvoiceId'>();\ninterface Receipt { accountId: z.output<typeof AccountId>; invoiceId: z.output<typeof InvoiceId> }",
      }],
      focusPath: "src/receipt.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
