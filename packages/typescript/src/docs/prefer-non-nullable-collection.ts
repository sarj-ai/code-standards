/** @fileoverview prefer-non-nullable-collection — the documentation and executable examples of `@sarj/prefer-non-nullable-collection`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_NON_NULLABLE_COLLECTION_DOCUMENTATION = {
  summary: "Suggest reviewing nullish arrays that use local empty-array defaults or a shared null-or-empty guard.",
  rationale: "A redundant nullish collection state spreads defaults and guards through consumers without carrying information.",
  remediation: "Use a non-null collection type and normalize omitted input to an empty collection at the boundary.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Automatic fixes remove only an explicit undefined union member from a required inline array property on an unused private nongeneric function parameter that already destructures it with an empty-array default. Null states, shared types, consumers, exports, comments, overloads and declaration files remain manual; runtime defaults are retained.",
    "Recognized defaults and guards are manual modeling prompts, not proof of equivalence for every caller or later use. Recognized exported wire shapes and unknown object escapes are excluded; preserve meaningful null states and boundary compatibility.",
    "Only inline object types or single unmerged top-level local declarations are resolved, using the type namespace. Array and ReadonlyArray names must be unshadowed built-ins; custom and imported constructors are not inferred. Local named, default and export-assignment type exports preserve ownership of their local interface and alias dependencies; arbitrary value exports remain opaque.",
    "Explicit exported variable annotations and signatures of local functions or constant callable aliases preserve input ownership, including callable signatures reached by an exported typeof query. Executable bodies, arbitrary value expressions, inferred exported types, class surfaces and ambiguous callable definitions are not resolved.",
  ],
  examples: [
    { id: "non-null-array", title: "Model an always-present collection", outcome: "no-match", files: [{ path: "src/search.ts", source: "interface Input { items: string[] } function search({ items }: Input) { return items.length; }" }], focusPath: "src/search.ts", expectedCount: 0, public: true },
    { id: "defaulted-nullish-array", title: "Do not retain a redundant nullish state", outcome: "match", files: [{ path: "src/search.ts", source: "interface Input { items: string[] | undefined } function search({ items = [] }: Input) { return items.length; }" }], focusPath: "src/search.ts", expectedCount: 1, public: true },
    { id: "exported-nullish-input", scenarioId: "exported-input", title: "Preserve an exported input contract", outcome: "no-match", files: [{ path: "src/search.ts", source: "interface Input { items: string[] | undefined } export type WireInput = Input; function search({ items = [] }: Input) { return items.length; }" }], focusPath: "src/search.ts", expectedCount: 0, public: true },
    { id: "private-nullish-input", scenarioId: "exported-input", title: "Review a private input with an empty default", outcome: "match", files: [{ path: "src/search.ts", source: "interface Input { items: string[] | undefined } type WireInput = Input; function search({ items = [] }: Input) { return items.length; }" }], focusPath: "src/search.ts", expectedCount: 1, public: true },
    {
      id: "safe-autofix",
      title: "Keep an unused private normalized collection non-nullable",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; function count({ items = [] }: { items: string[] | undefined }) { return items.length; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; function count({ items = [] }: { items: string[] }) { return items.length; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
