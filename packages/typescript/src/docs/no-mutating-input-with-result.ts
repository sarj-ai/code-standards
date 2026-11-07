/** @fileoverview no-mutating-input-with-result — the documentation and executable examples of `@sarj/no-mutating-input-with-result`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_MUTATING_INPUT_WITH_RESULT_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Return replacement object values instead of writing input fields in result-returning functions.",
  rationale: "A result-returning function that also writes a caller-owned object changes aliases outside the returned value, hiding its mutation contract.",
  remediation: "Return a fresh replacement and update the caller to use it, or expose an explicit in-place command returning void. Do not add a dummy return or discard the operation.",
  category: "correctness",
  limitations: [
    "Checks direct property assignments, updates and deletions on stable object parameters in explicitly nonvoid functions that visibly return a value. Property contracts must come from an inline type or a same-file unextended, undecorated interface, object type alias or class. Only declared mutable data fields are checked; readonly-field errors remain compiler-owned.",
    "Void/undefined/never commands, Promise<void>, receiver state, arbitrary imported/generic contracts, array inputs, nested descendants, parameter rebindings and alias-indirected writes remain excluded. Nested functions and class bodies have separate ownership and are not traversed. Generated/vendor files are excluded; maintained tests are checked.",
    "No automatic rewrite chooses cloning semantics or changes function callers. Explicit command/result APIs with an intentional mutation require a local explanation.",
  ],
  examples: [
    { id: "mutates-input", title: "A result does not undo the caller-visible write", outcome: "match", files: [{ path: "src/config.ts", source: "interface Config { enabled: boolean; } function enable(config: Config): Config { config.enabled = true; return config; }" }], focusPath: "src/config.ts", expectedCount: 1, public: true },
    { id: "returns-replacement", title: "Return the replacement explicitly", outcome: "no-match", files: [{ path: "src/config.ts", source: "interface Config { enabled: boolean; } function enable(config: Config): Config { return { ...config, enabled: true }; }" }], focusPath: "src/config.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
