/** @fileoverview no-cors-wildcard-with-credentials — the documentation and executable examples of `@sarj/no-cors-wildcard-with-credentials`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_CORS_WILDCARD_WITH_CREDENTIALS_DOCUMENTATION = {
  summary: "Review wildcard CORS origins combined with an explicit credentials opt-in.",
  rationale: "Browsers do not expose credentialed cross-origin responses when Access-Control-Allow-Origin is '*'. Credentialless requests can still use a wildcard even when Access-Control-Allow-Credentials is emitted, so review the intended caller contract.",
  remediation: "Use a trusted explicit origin for credentialed callers, or omit the credentials opt-in for a credentialless wildcard endpoint.",
  category: "correctness",
  defaultLevel: "warning",
  autofix: "none",
  references: ["https://fetch.spec.whatwg.org/#cors-protocol-and-credentials"],
  limitations: [
    "Options require a stable official cors default import or hono/cors named or namespace import, one literal object argument, literal origin '*', and credentials true. No-substitution templates and erased TypeScript literal wrappers preserve these values. Custom bindings, callbacks, arrays, conditional origins and dynamic options are excluded.",
    "Literal header maps use effective case-sensitive JavaScript property writes followed by native Headers combination of differently-cased header names. Unknown values/spreads/computed keys, accessors and non-null prototypes lose proof; literals used only inside object spreads are not reported independently.",
    "Manual set/setHeader/delete/removeHeader calls (including static computed method names) use direct identifier receivers and literal arguments in straight-line program or function bodies. Control-flow bodies, member receivers, aliases and unknown operations are excluded. Append requires a proven empty native Headers constructor or a preceding known write/removal.",
    "The rule reviews a local configuration contract, not actual request credentials or a data disclosure. Runtime patches, custom header method implementations, interprocedural mutation and later consumers are not resolved. No autofix.",
  ],
  examples: [
    {
      id: "trusted-origin-with-credentials",
      title: "Use a trusted origin for credentialed callers",
      outcome: "no-match",
      files: [{ path: "src/server.ts", source: "import cors from 'cors'; cors({ origin: 'https://app.example.com', credentials: true });" }],
      focusPath: "src/server.ts", expectedCount: 0, public: true,
    },
    {
      id: "wildcard-origin-with-credentials",
      title: "Review a wildcard that blocks access to credentialed responses",
      outcome: "match",
      files: [{ path: "src/server.ts", source: "import cors from 'cors'; cors({ origin: '*', credentials: true });" }],
      focusPath: "src/server.ts", expectedCount: 1, public: true,
    },
  ],
} as const satisfies RuleDocumentation;
