/** @fileoverview no-production-browser-source-maps — the documentation and executable examples of `@sarj/no-production-browser-source-maps`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_PRODUCTION_BROWSER_SOURCE_MAPS_DOCUMENTATION = {
  summary: "Next.js production browser source maps expose application source",
  rationale:
    "Next.js production browser source maps publish original client source and implementation details to every browser that can load the deployment.",
  remediation:
    "Leave productionBrowserSourceMaps disabled and upload private source maps directly to the error-monitoring service during the build.",
  category: "security",
  autofix: "safe",
  limitations: [
    "Automatic boolean changes are withheld when the module contains explicit TypeScript or JSDoc contracts; those contracts can constrain an aliased property to literal true. Plain objects and as const inference remain fixable.",
    "Only a literal true in the effective property of a directly exported object, unescaped const alias, or isolated module.exports object is reported. Wrappers, factories, spreads, dynamic computed keys and mutations are not inferred.",
  ],
  examples: [
    {
      id: "private-source-maps",
      title: "Keep browser source maps private",
      outcome: "no-match",
      files: [{ path: "next.config.mjs", source: "export default { productionBrowserSourceMaps: false };\n" }],
      focusPath: "next.config.mjs",
      expectedCount: 0,
      public: true,
    },
    {
      id: "public-source-maps",
      title: "Do not publish production browser source maps",
      outcome: "match",
      files: [{ path: "next.config.mjs", source: "export default { productionBrowserSourceMaps: true };\n" }],
      focusPath: "next.config.mjs",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "next.config.ts", source: "export default { productionBrowserSourceMaps: true };" }],
      fixedFiles: [{ path: "next.config.ts", source: "export default { productionBrowserSourceMaps: false };" }],
      focusPath: "next.config.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
