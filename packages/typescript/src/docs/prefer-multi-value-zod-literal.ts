/** @fileoverview prefer-multi-value-zod-literal — the documentation and executable examples of `@sarj/prefer-multi-value-zod-literal`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_MULTI_VALUE_ZOD_LITERAL_DOCUMENTATION = {
  defaultLevel: "error",
  summary:
    "Use the Zod 4 multi-value literal API instead of a union of literal schemas.",
  rationale:
    "One multi-value literal expresses the same closed value domain without repeated schema wrappers.",
  remediation:
    "Use z.literal([value1, value2, ...]) for a modern Zod 4 value-domain contract. Preserve required union introspection or error-shape contracts with an explained local exception.",
  category: "maintainability",
  autofix: "none",
  limitations: [
    "Bare zod imports are analyzed only when the rule option explicitly declares zodMajorVersion: 4; explicit zod/v4 entrypoints are self-declaring.",
    "All-string domains are left to zod/prefer-enum-over-literal-union.",
    "Migration remains manual: supported global constructor hooks observe the original literal/literal/union construction sequence even for an unused private schema. ZodLiteral and ZodUnion also expose different introspection APIs and validation error shapes.",
  ],
  examples: [
    {
      id: "multi-value",
      title: "Use one multi-value literal",
      outcome: "no-match",
      files: [
        {
          path: "src/schema.ts",
          source:
            "import { z } from 'zod/v4'; export const Version = z.literal([1, 2, 3]);",
        },
      ],
      focusPath: "src/schema.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "literal-union",
      title: "Avoid repeated literal wrappers",
      outcome: "match",
      files: [
        {
          path: "src/schema.ts",
          source:
            "import { z } from 'zod/v4'; export const Version = z.union([z.literal(1), z.literal(2), z.literal(3)]);",
        },
      ],
      focusPath: "src/schema.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "private-schema-migration",
      title: "Review constructor hooks before migrating a private schema",
      outcome: "match",
      files: [
        {
          path: "src/autofix-example.ts",
          source:
            'import { z } from "zod/v4"; const VersionSchema = z.union([z.literal(1), z.literal(2)]);',
        },
      ],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
