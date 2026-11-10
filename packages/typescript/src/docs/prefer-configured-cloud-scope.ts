/** @fileoverview prefer-configured-cloud-scope — documentation and executable deployment-scope examples. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_CONFIGURED_CLOUD_SCOPE_DOCUMENTATION = {
  summary:
    "Prefer validated deployment configuration for account scope in outgoing cloud management requests.",
  rationale:
    "A source-literal cloud account scope pins operational requests to one deployment even when the credential or environment changes.",
  remediation:
    "Read the account ID through one shared settings object validated by a Zod schema at startup, then import or inject that parsed object into consumers. Required values must fail before remote effects. Preserve independent security allowlists; an environment read alone is not validation.",
  category: "correctness",
  defaultLevel: "warning",
  autofix: "none",
  requiresTypeInformation: false,
  limitations: [
    "Initial coverage is canonical HTTPS Cloudflare v4 account-management URLs with a 32-character hexadecimal account segment sent to an unshadowed fetch, stable const alias, or fetch-default parameter. Other providers, SDKs, arbitrary endpoints, Worker names and resource IDs require separate evidence.",
    "Follows bounded same-file const aliases, concatenations and template strings. One-argument native URL wrappers are supported only for fully known absolute account URLs whose native normalization leaves the text unchanged. Local/imported constructors, dynamic constructor arguments, relative-base URLs, Request objects, unknown accounts, fallback expressions, function returns and cross-file values remain unreported.",
    "Native URL constructor/prototype mutation or capability capture outside new/typeof vetoes wrapper folding. Escaping/dynamic global receiver access and ambient eval/Function also leave URL semantics unknown. A stored URL must be nonexported, have at most 128 references, and every runtime read must be a direct native fetch argument; mutable instances, aliases, injected transports and other escapes remain unknown. These URL limits do not hide independent direct string fetch findings. Direct writes to ambient fetch or its global receivers retain their existing veto; indirect runtime monkeypatches are not modeled.",
    "Analysis stops at 16 nested expressions or fetch aliases, 256 URL-expression visits per request, 128 string fragments or 8,192 UTF-16 code units of assembled URL text. These limits deliberately leave more complex expressions unreported.",
    "Scripts remain covered. Test/fixture and generated files are excluded. Comparisons, schemas, allowlists and unused URL strings do not produce findings. Each originating account literal is reported at most once per file.",
    "This is a warning without an automatic fix: the deployment configuration boundary and independent authorization policy require review. Application code should import validated configuration as required by no-raw-env; browser-exposed variables must never contain secrets.",
  ],
  references: [
    "https://developers.cloudflare.com/workers/wrangler/system-environment-variables/",
    "https://eslint.org/docs/latest/rules/no-restricted-syntax",
  ],
  examples: [
    {
      id: "literal-account-scope",
      title: "Move outgoing account scope into deployment configuration",
      outcome: "match",
      files: [
        {
          path: ".github/scripts/publish.mjs",
          source:
            "const accountId = '0123456789abcdef0123456789abcdef';\nconst base = `https://api.cloudflare.com/client/v4/accounts/${accountId}`;\nexport async function publish(path, request = fetch) { return request(`${base}/${path}`); }",
        },
      ],
      focusPath: ".github/scripts/publish.mjs",
      expectedCount: 1,
      public: true,
    },
    {
      id: "validated-account-scope",
      title: "Parse one shared settings object with Zod before requests",
      outcome: "no-match",
      files: [
        {
          path: ".github/scripts/publish.mjs",
          source:
            "import { settings } from '../../src/env.mjs';\nconst base = `https://api.cloudflare.com/client/v4/accounts/${settings.CLOUDFLARE_ACCOUNT_ID}`;\nexport async function publish(path, request = fetch) { return request(`${base}/${path}`); }\nexport async function list(request = fetch) { return request(`${base}/workers/scripts`); }",
        },
        {
          path: "src/env.mjs",
          source:
            "import { z } from 'zod';\nconst SettingsSchema = z.object({ CLOUDFLARE_ACCOUNT_ID: z.string().length(32).regex(/^[a-fA-F0-9]+$/u) });\nexport const settings = SettingsSchema.parse(process.env);",
        },
      ],
      focusPath: ".github/scripts/publish.mjs",
      expectedCount: 0,
      public: true,
    },
    {
      id: "native-url-literal-account",
      scenarioId: "native-url-account",
      title: "A native URL wrapper still fixes the outgoing account in source",
      outcome: "match",
      files: [
        {
          path: "src/cloud-client.ts",
          source:
            'export function list() { return fetch(new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts")); }',
        },
      ],
      focusPath: "src/cloud-client.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "native-url-configured-account",
      scenarioId: "native-url-account",
      title: "Supply the account from shared Zod-validated settings",
      outcome: "no-match",
      files: [
        {
          path: "src/cloud-client.ts",
          source:
            'import { settings } from "./env.js";\nexport function list() { return fetch(new URL(`https://api.cloudflare.com/client/v4/accounts/${settings.CLOUDFLARE_ACCOUNT_ID}/workers/scripts`)); }',
        },
        {
          path: "src/env.ts",
          source:
            'import { z } from "zod";\nconst SettingsSchema = z.object({ CLOUDFLARE_ACCOUNT_ID: z.string().length(32).regex(/^[a-fA-F0-9]+$/u) });\nexport const settings = SettingsSchema.parse(process.env);',
        },
      ],
      focusPath: "src/cloud-client.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
