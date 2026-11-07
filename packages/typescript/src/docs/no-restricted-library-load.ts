/** @fileoverview no-restricted-library-load — the documentation and executable examples of `@sarj/no-restricted-library-load`. */

import type { RuleDocumentation } from "../documentation.js";

export interface RestrictedLibrary {
  readonly id: string;
  readonly module: string;
  readonly replacement: string;
  readonly note?: string;
}

export type Options = readonly [
  {
    libraries: readonly RestrictedLibrary[];
  },
];

export const NO_RESTRICTED_LIBRARY_LOAD_DOCUMENTATION = {
  summary: "Apply configured library restrictions to literal runtime loads and CommonJS resolution references.",
  rationale: "Dynamic imports, CommonJS loads, and package resolution checks can bypass library restrictions enforced for static imports.",
  remediation: "Use the configured replacement for the runtime dependency reference; resolution checks do not themselves load a module.",
  category: "architecture",
  limitations: ["Only literal dynamic imports, unshadowed CommonJS loads/resolution calls, and runtime TypeScript import-equals declarations are checked; erased type imports are excluded. A configured restriction list is required."],
  examples: [
    { id: "configured-replacement", title: "Use the configured library replacement", outcome: "no-match", files: [{ path: "src/client.ts", source: "import ky from 'ky'; const client = ky;" }], focusPath: "src/client.ts", expectedCount: 0, public: true, ruleOptions: [{ libraries: [{ id: "LIB101", module: "axios", replacement: "Ky" }] }] },
    { id: "runtime-load", title: "Do not load a restricted library at runtime", outcome: "match", files: [{ path: "src/client.ts", source: "const client = require('axios');" }], focusPath: "src/client.ts", expectedCount: 1, public: true, ruleOptions: [{ libraries: [{ id: "LIB101", module: "axios", replacement: "Ky" }] }] },
    { id: "static-import-owned-upstream", title: "Leave static restrictions to the owning import rule", outcome: "no-match", files: [{ path: "src/client.ts", source: "import axios from 'axios';" }], focusPath: "src/client.ts", expectedCount: 0, ruleOptions: [{ libraries: [{ id: "LIB101", module: "axios", replacement: "Ky" }] }] },
    {
      id: "checked-runtime-load",
      title: "Identify the exact restricted runtime argument",
      outcome: "match",
      files: [{ path: "src/client.ts", source: "const client = require('axios');" }],
      focusPath: "src/client.ts",
      expectedCount: 1,
      ruleOptions: [{ libraries: [{ id: "LIB101", module: "axios", replacement: "Ky" }] }],
      expectedDiagnostics: [{
        messageId: "restrictedLibraryLoad",
        message: "LIB101: Replace this runtime dependency reference to axios with Ky.",
        location: { line: 1, column: 24, end: { line: 1, column: 31 } },
        automaticFix: false,
        suggestions: [],
      }],
    },
  ],
} as const satisfies RuleDocumentation<Options>;
