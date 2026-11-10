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
    "Host markers, assignment targets, tests, ordinary scripts and build config retain their policy exemptions. Boundary-named modules, including env.mjs and settings.ts, are checked. Native named process env imports and simple const { env } = process aliases follow the same read policy; foreign, type-only, shadowed and mutable sources are not inferred.",
    "Each raw value must reach a parse/safeParse argument or supported environment loader, directly or through stable nonexported const aliases whose every use reaches validation. Directly awaited parseAsync/safeParseAsync calls also count; unawaited promises or later await-through-alias flows do not. Conditional tests and logical-and conditions are control inputs, not the parsed result; value arms and existing nullish/logical-or defaults remain supported.",
    "Simple nonexported const object patterns may select static keys into plain identifier bindings when every ordinary read of each selected field reaches validation. Type-only references are ignored. Native whole-environment host marker keys retain their exemptions, including through stable aliases; an arbitrary raw field with a marker-shaped property does not. Unused, unparsed, escaping or later-written ordinary fields fail the proof. Opaque computed keys, defaults, rest and nested patterns remain unsupported.",
    "Renamed value imports of createEnv from @t3-oss/env-core or @t3-oss/env-nextjs retain loader ownership. Existing unresolved project parse/safeParse and legacy createEnv protocols remain accepted; this is not a proof of their implementation. A narrowly proven private identity adapter only forwards its input: that input must still reach an actual parser.",
    "Identity-adapter detection is limited to an explicit module, no namespace or runtime eval reference, one stable nonexported binding and a synchronous function whose sole plain identifier parameter is returned unchanged. An object may contain only one or two unique own parse/safeParse identity methods, with every ordinary receiver reference a direct method call. Exported/mutable/escaped receivers, spreads, getters, duplicate/opaque keys, extra methods, imported loaders, real Zod wrappers and optional/awaited adapter-result ambiguity retain the existing protocol. The proof stops after 128 binding references, 512 module references or 32 enclosing AST parents; it adds no whole-program library-provenance requirement.",
    "Only unshadowed Number/String/Boolean/BigInt calls and one-argument native JSON decoding are traversed as preprocessing. JSON.parse alone does not validate settings: its decoded result must itself reach the parser. JSON revivers and arbitrary calls cannot consume raw settings under this preprocessing exemption.",
    "This is bounded same-file syntax analysis (24 flow steps, 128 selected fields per pattern, 128 reads per binding and 512 total expression/field visits per raw read; whole-environment host-marker provenance follows at most 16 aliases); flows exceeding these budgets are unreported. It does not prove a parser's implementation, cross-file schemas, schema completeness, safeParse failure handling or a project-wide singleton. Handle safeParse failure before exposing result.data; prefer throwing parse at startup. Nested component settings and separate server/client runtime boundaries remain valid.",
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
    {
      id: "native-env-import-read",
      scenarioId: "native-env-import",
      title: "Native env import aliases still need validation",
      outcome: "match",
      files: [
        {
          path: "src/database.ts",
          source:
            'import { env as raw } from "node:process";\nexport const databaseUrl = raw.DATABASE_URL;',
        },
      ],
      focusPath: "src/database.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "native-env-import-validated",
      scenarioId: "native-env-import",
      title: "Parse the imported environment once and share settings",
      outcome: "no-match",
      files: [
        {
          path: "src/database.ts",
          source:
            'import { settings } from "./env.js";\nexport const databaseUrl = settings.DATABASE_URL;',
        },
        {
          path: "src/env.ts",
          source:
            'import { env as raw } from "node:process";\nimport { z } from "zod";\nconst SettingsSchema = z.object({ DATABASE_URL: z.url() });\nexport const settings = SettingsSchema.parse(raw);',
        },
      ],
      focusPath: "src/env.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "json-decoding-without-validation",
      scenarioId: "json-settings",
      title: "JSON decoding does not validate the settings contract",
      outcome: "match",
      files: [
        {
          path: "src/env.ts",
          source: "export const settings = JSON.parse(process.env.SETTINGS_JSON);",
        },
      ],
      focusPath: "src/env.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "json-decoding-then-validation",
      scenarioId: "json-settings",
      title: "Validate decoded environment JSON with the actual schema",
      outcome: "no-match",
      files: [
        {
          path: "src/env.ts",
          source:
            'import { z } from "zod";\nconst SettingsSchema = z.object({ API_ORIGIN: z.url() });\nexport const settings = SettingsSchema.parse(JSON.parse(process.env.SETTINGS_JSON));',
        },
      ],
      focusPath: "src/env.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "raw-input-controls-effects",
      scenarioId: "conditional-settings",
      title: "A raw conditional input is not the value reaching the parser",
      outcome: "match",
      files: [
        {
          path: "src/env.ts",
          source:
            'import { z } from "zod";\nconst SettingsSchema = z.object({ API_ORIGIN: z.url() });\nexport const settings = SettingsSchema.parse(process.env.LOAD_REMOTE ? fetch("https://example.test/config") : {});',
        },
      ],
      focusPath: "src/env.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "validated-input-controls-effects",
      scenarioId: "conditional-settings",
      title: "Parse the control setting before remote effects",
      outcome: "no-match",
      files: [
        {
          path: "src/env.ts",
          source:
            'import { z } from "zod";\nconst SettingsSchema = z.object({ LOAD_REMOTE: z.enum(["0", "1"]).transform(value => value === "1") });\nexport const settings = SettingsSchema.parse(process.env);\nif (settings.LOAD_REMOTE) await fetch("https://example.test/config");',
        },
      ],
      focusPath: "src/env.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "async-settings-promise",
      scenarioId: "async-settings",
      title: "An unfinished parser promise is not startup settings",
      outcome: "match",
      files: [
        {
          path: "src/env.ts",
          source:
            'import { z } from "zod";\nconst SettingsSchema = z.object({ API_KEY: z.string().min(1) });\nexport const settings = SettingsSchema.parseAsync(process.env);',
        },
      ],
      focusPath: "src/env.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "async-settings-awaited",
      scenarioId: "async-settings",
      title: "Await parsing before exporting the shared settings object",
      outcome: "no-match",
      files: [
        {
          path: "src/env.ts",
          source:
            'import { z } from "zod";\nconst SettingsSchema = z.object({ API_KEY: z.string().min(1) });\nexport const settings = await SettingsSchema.parseAsync(process.env);',
        },
      ],
      focusPath: "src/env.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "selected-fields-raw-escape",
      scenarioId: "selected-settings-fields",
      title: "Parsing one selected field does not validate another raw export",
      outcome: "match",
      files: [
        {
          path: "src/env.ts",
          source:
            'import { env as raw } from "node:process";\nimport { z } from "zod";\nconst SettingsSchema = z.object({ API_KEY: z.string().min(1) });\nconst { API_KEY, API_ORIGIN } = raw;\nexport const settings = SettingsSchema.parse({ API_KEY });\nexport const unparsedOrigin = API_ORIGIN;',
        },
      ],
      focusPath: "src/env.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "selected-fields-validated",
      scenarioId: "selected-settings-fields",
      title: "Validate every selected ordinary field and reuse the parsed result",
      outcome: "no-match",
      files: [
        {
          path: "src/env.ts",
          source:
            'import { env as raw } from "node:process";\nimport { z } from "zod";\nconst SettingsSchema = z.object({ API_KEY: z.string().min(1), API_ORIGIN: z.url() });\nconst { API_KEY, API_ORIGIN } = raw;\nexport const settings = SettingsSchema.parse({ API_KEY, API_ORIGIN });',
        },
      ],
      focusPath: "src/env.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "identity-loader-without-parser",
      scenarioId: "closed-identity-adapter",
      title: "A local identity adapter does not validate environment input",
      outcome: "match",
      files: [
        {
          path: "src/env.ts",
          source:
            "const createEnv = input => input;\nexport const settings = createEnv(process.env);",
        },
      ],
      focusPath: "src/env.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "identity-loader-before-real-parser",
      scenarioId: "closed-identity-adapter",
      title: "An identity adapter can forward into the actual Zod parser",
      outcome: "no-match",
      files: [
        {
          path: "src/env.ts",
          source:
            'import { z } from "zod";\nconst SettingsSchema = z.object({ API_KEY: z.string().min(1) });\nconst createEnv = input => input;\nexport const settings = SettingsSchema.parse(createEnv(process.env));',
        },
      ],
      focusPath: "src/env.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
