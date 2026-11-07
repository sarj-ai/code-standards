/** @fileoverview no-credential-in-browser-storage — the documentation and executable examples of `@sarj/no-credential-in-browser-storage`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_CREDENTIAL_IN_BROWSER_STORAGE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Do not write credential-named values to browser storage or script-readable cookies.",
  rationale:
    "localStorage, sessionStorage and cookies written through document.cookie are readable by any script on the origin, so one injected script can copy the credential and replay it elsewhere.",
  remediation:
    "Keep the credential on the server and send it as an httpOnly, Secure, SameSite cookie set by a server response, or hold a short-lived token in memory only.",
  category: "security",
  limitations: [
    "Only static keys and cookie names whose words name an access credential (token, secret, password, jwt, credential, api key) are checked.",
    "Storage wrappers, computed keys and values stored under neutral names are not followed.",
  ],
  examples: [
    {
      id: "server-cookie",
      title: "Store a non-credential preference in localStorage",
      outcome: "no-match",
      files: [{ path: "src/theme.ts", source: "localStorage.setItem(\"sidebar-collapsed\", \"true\");\n" }],
      focusPath: "src/theme.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "token-in-local-storage",
      title: "Do not store an access token in localStorage",
      outcome: "match",
      files: [{
        path: "src/session.ts",
        source: "export function remember(token: string): void {\n  localStorage.setItem(\"accessToken\", token);\n}\n",
      }],
      focusPath: "src/session.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
