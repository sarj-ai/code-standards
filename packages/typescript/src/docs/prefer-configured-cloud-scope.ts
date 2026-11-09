/** @fileoverview prefer-configured-cloud-scope — documentation and executable deployment-scope examples. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_CONFIGURED_CLOUD_SCOPE_DOCUMENTATION = {
  summary: "Prefer validated deployment configuration for account scope in outgoing cloud management requests.",
  rationale: "A source-literal cloud account scope pins operational requests to one deployment even when the credential or environment changes.",
  remediation: "Read the account ID from environment variables or injected configuration, validate it at startup, and pass the validated value to the request. Preserve independent security allowlists and fail closed when required configuration is missing.",
  category: "correctness",
  defaultLevel: "warning",
  autofix: "none",
  requiresTypeInformation: false,
  limitations: [
    "Initial coverage is canonical HTTPS Cloudflare v4 account-management URLs with a 32-character hexadecimal account segment sent to an unshadowed fetch, stable const alias, or fetch-default parameter. Other providers, SDKs, arbitrary endpoints, Worker names and resource IDs require separate evidence.",
    "Follows bounded same-file const aliases, concatenations and template strings; an unknown account, mutable binding, function return, object property, fallback expression, URL/Request object or cross-file value is not inferred. Direct writes to the ambient fetch or its global receivers veto findings; indirect runtime monkeypatches are not modeled.",
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
      files: [{
        path: ".github/scripts/publish.mjs",
        source: "const accountId = '0123456789abcdef0123456789abcdef';\nconst base = `https://api.cloudflare.com/client/v4/accounts/${accountId}`;\nexport async function publish(path, request = fetch) { return request(`${base}/${path}`); }",
      }],
      focusPath: ".github/scripts/publish.mjs",
      expectedCount: 1,
      public: true,
    },
    {
      id: "validated-account-scope",
      title: "Pass validated deployment configuration to the request",
      outcome: "no-match",
      files: [{
        path: ".github/scripts/publish.mjs",
        source: "import { env } from './env.mjs';\nconst base = `https://api.cloudflare.com/client/v4/accounts/${env.CLOUDFLARE_ACCOUNT_ID}`;\nexport async function publish(path, request = fetch) { return request(`${base}/${path}`); }",
      }],
      focusPath: ".github/scripts/publish.mjs",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
