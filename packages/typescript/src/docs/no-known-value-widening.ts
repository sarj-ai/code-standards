/** @fileoverview no-known-value-widening — the documentation and executable examples of `@sarj/no-known-value-widening`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_KNOWN_VALUE_WIDENING_DOCUMENTATION = {
  summary: "Preserve a known value's contract instead of widening a local binding to unknown, object, or an unknown-valued dictionary.",
  rationale: "Erasing a typed value's fields forces downstream code to rediscover the same contract through casts, reflection, or representation checks.",
  remediation: "Keep the inferred type, select the required domain fields, or use satisfies to check compatibility without erasing evidence.",
  category: "maintainability",
  requiresTypeInformation: true,
  references: ["https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/src/rules/no-known-value-widening.ts"],
  autofix: "safe",
  limitations: [
    "Requires TypeScript type information. Checks annotated local const bindings with independently known identifier, nonempty literal or monomorphic-call initializers; complete readonly private field writes and proven closed literal registries are also inspected. Parameters, direct exports, computed SDK/schema contracts, uncertain contextual inference and assertions are excluded.",
    "Known-value erasure checks target unknown, object, and index-only dictionaries with unknown values. Separate finite-key guidance applies to proven closed registries with concrete values. Typed dynamic registries, finite-key records, empty accumulators, unknown external input and incomplete private-field write sets are preserved. Finite-key guidance requires a closed local literal with no mutations, escapes or unknown invocation receivers.",
    "Intentional type erasure at a real abstraction boundary needs a local suppression explaining that boundary. New initializer, field and registry cases remain manual. Automatic fixes remove the annotation only from an unused private identifier-initialized binding in a module or block; referenced bindings retain their declared contract for manual review.",
  ],
  examples: [
    { id: "erased-tool", title: "A dictionary erases a known tool contract", outcome: "match", files: [{ path: "src/tool.ts", source: "type Tool = { name: string; enabled: boolean };\ndeclare const tool: Tool;\nconst fields: Record<string, unknown> = tool;" }], focusPath: "src/tool.ts", expectedCount: 1, public: true },
    { id: "retained-tool", title: "Retain the tool's fields", outcome: "no-match", files: [{ path: "src/tool.ts", source: "type Tool = { name: string; enabled: boolean };\ndeclare const tool: Tool;\nconst fields = tool;" }], focusPath: "src/tool.ts", expectedCount: 0, public: true },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; declare const tool: { name: string }; const fields: unknown = tool;" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; declare const tool: { name: string }; const fields = tool;" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
    {"id": "finite-registry-before", "scenarioId": "finite-registry", "title": "Preserve a closed registry key set — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "const handlers: Record<string, () => void> = { start() {} }; handlers.start();"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "finite-registry-after", "scenarioId": "finite-registry", "title": "Preserve a closed registry key set — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "type Command = 'start'; const handlers = { start() {} } satisfies Record<Command, () => void>; handlers.start();"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
    {"id": "private-storage-before", "scenarioId": "private-storage", "title": "Retain a completely owned storage contract — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "class Store { readonly #value: unknown = { id: 'u1' }; read() { return this.#value; } }"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "private-storage-after", "scenarioId": "private-storage", "title": "Retain a completely owned storage contract — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "class Store { readonly #value = { id: 'u1' }; read() { return this.#value; } }"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
    {"id": "factory-initializer-before", "scenarioId": "factory-initializer", "title": "Retain the monomorphic factory contract — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "declare function load(): { id: string }; const value: unknown = load();"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "factory-initializer-after", "scenarioId": "factory-initializer", "title": "Retain the monomorphic factory contract — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "declare function load(): { id: string }; const value = load();"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
    {"id": "literal-initializer-before", "scenarioId": "literal-initializer", "title": "Retain the independently known literal contract — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "const value: unknown = { id: 'u1' };"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "literal-initializer-after", "scenarioId": "literal-initializer", "title": "Retain the independently known literal contract — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "const value = { id: 'u1' };"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
  ],
} as const satisfies RuleDocumentation;
