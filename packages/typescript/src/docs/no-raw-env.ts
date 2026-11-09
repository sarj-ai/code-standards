/** @fileoverview no-raw-env — the documentation and executable examples of `@sarj/no-raw-env`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_RAW_ENV_DOCUMENTATION = {
  summary:
    "Disallow direct `process.env` and `import.meta.env` reads outside validated boundaries.",
  rationale:
    "Raw environment reads are untyped and defer invalid configuration failures until use. One shared validated settings object gives consumers a consistent startup configuration.",
  remediation:
    "Define a Zod settings schema, call SettingsSchema.parse(process.env) once at startup, and export or inject that single parsed settings object. Use Pydantic/Pydantic Settings for the equivalent Python boundary. Required values must fail before remote effects; preserve independent security policy and existing optional defaults.",
  category: "correctness",
  limitations: [
    "Host markers, assignment targets, tests, ordinary scripts and build config retain their policy exemptions. Boundary-named modules, including env.mjs and settings.ts, are checked. A boundary filename or schema declaration alone does not exempt raw reads: each read must flow through a parse/safeParse/createEnv argument, directly or through stable nonexported const aliases whose every use reaches validation. Only unshadowed Number/String/Boolean/BigInt calls are traversed as scalar coercions; arbitrary calls cannot consume raw settings before the parser.",
    "This is bounded same-file syntax analysis (24 flow steps, 128 reads per alias and 512 total expression visits per raw read); flows exceeding these budgets are unreported. It does not prove a parser's implementation, cross-file schemas, schema completeness, safeParse failure handling or a project-wide singleton. Handle safeParse failure before exposing result.data; prefer throwing parse at startup. Nested component settings and separate server/client runtime boundaries remain valid.",
    "Assignment-target exemptions also include compound writes that read the previous value. Whole-environment spreads outside boundary modules retain the existing forwarding exemption; a spread inside a boundary must also reach its parser. No automatic rewrite.",
  ],
  examples: [
    {
      id: "validated-environment",
      title: "Parse once and reuse one settings object",
      outcome: "no-match",
      files: [
        {
          path: "src/database.ts",
          source:
            "import { settings } from './env.js';\nexport const primaryUrl = settings.DATABASE_URL;\nexport const replicaUrl = settings.DATABASE_URL;",
        },
        {
          path: "src/env.ts",
          source:
            "import { z } from 'zod';\nconst SettingsSchema = z.object({ DATABASE_URL: z.url() });\nexport const settings = SettingsSchema.parse(process.env);",
        },
      ],
      focusPath: "src/env.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "raw-environment-read",
      title: "Declaring a schema does not validate a raw export",
      outcome: "match",
      files: [
        {
          path: "src/env.ts",
          source:
            "import { z } from 'zod';\nconst SettingsSchema = z.object({ DATABASE_URL: z.url() });\nexport const settings = { DATABASE_URL: process.env.DATABASE_URL };",
        },
      ],
      focusPath: "src/env.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
