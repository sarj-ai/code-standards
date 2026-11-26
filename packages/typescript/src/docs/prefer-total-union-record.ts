/** @fileoverview prefer-total-union-record — the documentation and executable examples of `@sarj/prefer-total-union-record`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_TOTAL_UNION_RECORD_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Declare a total record for closed registries indexed by a finite string union.",
  rationale: "A string index permits a table to omit a union member, so adding a state can silently reach a fallback.",
  remediation: "Use satisfies Record<Key, Value> with the domain union, and supply an entry for each member. Review any fallback separately.",
  category: "correctness",
  requiresTypeInformation: true,
  limitations: [
    "Checks module-private const object literals with a built-in Record<string, V> or string index signature and fixed initializer keys. Excludes whole-table uses, writes, optional accesses and calls through the table.",
    "After ignoring null and undefined, every computed index must resolve to string literals. Requires at least two distinct computed keys and at most 64 keys across all reads.",
  ],
  examples: [
    { id: "total-record-before", scenarioId: "total-record", title: "A string index permits a missing state", outcome: "match", files: [{ path: "label.ts", source: "import type { State } from './states.js';\nconst LABELS: Record<string, string> = { failed: 'Failed', passed: 'Passed' };\nexport const label = (state: State) => LABELS[state] ?? 'Pending';" }, { path: "states.ts", source: "export type State = 'failed' | 'passed' | 'running';" }], focusPath: "label.ts", expectedCount: 1, public: true },
    { id: "total-record-after", scenarioId: "total-record", title: "A total record requires every state", outcome: "no-match", files: [{ path: "label.ts", source: "import type { State } from './states.js';\nconst LABELS = { failed: 'Failed', passed: 'Passed', running: 'Pending' } as const satisfies Record<State, string>;\nexport const label = (state: State) => LABELS[state];" }, { path: "states.ts", source: "export type State = 'failed' | 'passed' | 'running';" }], focusPath: "label.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
