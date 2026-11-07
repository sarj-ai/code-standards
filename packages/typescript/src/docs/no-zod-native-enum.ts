/** @fileoverview no-zod-native-enum — the documentation and executable examples of `@sarj/no-zod-native-enum`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_ZOD_NATIVE_ENUM_DOCUMENTATION = {
  summary:
    'Disallow `z.nativeEnum()` (and `z.enum()` over a TypeScript enum); use `z.enum(["a", "b"])` with a string-literal union instead.',
  rationale:
    "The project prefers literal-first schema definitions. nativeEnum also accepts plain enum-like objects, so this is an explicit declaration policy, not proof that every call duplicates a TypeScript enum's runtime object.",
  remediation:
    "Pass string literals directly to `z.enum` and derive the TypeScript type with `z.infer`.",
  category: "maintainability",
  autofix: "none",
  limitations: [
    "Migration remains manual: enum-like object keys and supported global constructor hooks remain observable even for unused private schemas. Equal key/value objects still expose the changed nativeEnum versus enum constructor call through a hook stack.",
  ],
  examples: [
    {
      id: "zod-literal-enum",
      title: "Declare string values directly in Zod",
      outcome: "no-match",
      files: [
        {
          path: "src/status.ts",
          source:
            'import { z } from "zod"; const S = z.enum(["active", "inactive"]);',
        },
      ],
      focusPath: "src/status.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "zod-native-enum",
      title: "Declare literal values instead of an enum-like object",
      outcome: "match",
      files: [
        {
          path: "src/status.ts",
          source:
            'import { z } from "zod"; const S = z.nativeEnum({ Active: "active", Inactive: "inactive" });',
        },
      ],
      focusPath: "src/status.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "imported-typescript-enum",
      scenarioId: "imported-enum",
      title: "Do not hide an imported TypeScript enum behind z.enum",
      outcome: "match",
      files: [
        {
          path: "src/status-values.ts",
          source:
            "export enum Status { Active = 'active', Inactive = 'inactive' }",
        },
        {
          path: "src/status.ts",
          source:
            "import { z } from 'zod'; import { Status } from './status-values.js';\nexport const StatusSchema = z.enum(Status);",
        },
      ],
      installedDependencies: [{ module: "zod", version: "4.6.7" }],
      focusPath: "src/status.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "schema-owned-string-values",
      scenarioId: "imported-enum",
      title: "Let the schema own its literal value domain",
      outcome: "no-match",
      files: [
        {
          path: "src/status.ts",
          source:
            "import { z } from 'zod';\nexport const StatusSchema = z.enum(['active', 'inactive']);",
        },
      ],
      installedDependencies: [{ module: "zod", version: "4.6.7" }],
      focusPath: "src/status.ts",
      expectedCount: 0,
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
            'import { z } from "zod/v4"; const StatusSchema = z.nativeEnum({ Active: "active", Inactive: "inactive" });',
        },
      ],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
