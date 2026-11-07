/** @fileoverview sole-export-matches-filename — the documentation and executable examples of `@sarj/sole-export-matches-filename`. */

import type { RuleDocumentation } from "../documentation.js";

export const SOLE_EXPORT_MATCHES_FILENAME_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Make a module filename reflect its sole named public runtime export.",
  rationale: "When a module owns one runtime responsibility, matching names make that responsibility directly discoverable.",
  remediation: "Name the module for the exported responsibility, using the full kebab-case export name; otherwise colocate genuinely related exports.",
  category: "maintainability",
  limitations: [
    "Framework entrypoints, generic stems covered by no-generic-single-export-module, tests, generated files, anonymous defaults, CommonJS, unresolved re-exports, and emission-dependent exports are excluded.",
    "The rule compares the primary filename stem and preserves a single private underscore prefix and conventional suffixes such as .server or .worker. Supporting types do not exempt a sole runtime export; public runtime aliases count as distinct exports.",
    "Exported destructuring patterns are excluded rather than undercounted as public exports.",
    "Next.js metadata routes, instrumentation, and other Next.js and Astro entrypoint exemptions require the nearest package.json to declare the framework, a conventional entrypoint path, and its expected runtime export. Custom routing roots and pageExtensions are not inferred.",
  ],
  examples: [
    { id: "matching-class", title: "Match a class and module", outcome: "no-match", files: [{ path: "src/artifact-store.ts", source: "export class ArtifactStore {}" }], focusPath: "src/artifact-store.ts", expectedCount: 0, public: true },
    { id: "mismatched-class", title: "Do not hide a sole class behind another filename", outcome: "match", files: [{ path: "src/artifacts.ts", source: "export class ArtifactStore {}" }], focusPath: "src/artifacts.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
