/** @fileoverview no-generic-single-export-module — the documentation and executable examples of `@sarj/no-generic-single-export-module`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_GENERIC_SINGLE_EXPORT_MODULE_DOCUMENTATION = {
  summary: "Disallow generic module stems when one runtime export already names the responsibility.",
  rationale: "A generic filename hides the sole exported responsibility and makes navigation less descriptive.",
  remediation: "Choose a responsibility-bearing module name or colocate the export with its domain.",
  category: "maintainability",
  limitations: ["Only the fixed generic-stem vocabulary with exactly one public runtime export is checked; exported destructuring patterns are excluded rather than undercounted."],
  examples: [
    { id: "responsibility-named-module", title: "Name the module after its export", outcome: "no-match", files: [{ path: "src/parse-order.ts", source: "export function parseOrder() { return {}; }" }], focusPath: "src/parse-order.ts", expectedCount: 0, public: true },
    { id: "generic-module-name", title: "Do not hide one export in a generic module", outcome: "match", files: [{ path: "src/utils.ts", source: "export function parseOrder() { return {}; }" }], focusPath: "src/utils.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
