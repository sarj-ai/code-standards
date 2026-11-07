/** @fileoverview no-storage-in-stateless-modules — the documentation and executable examples of `@sarj/no-storage-in-stateless-modules`. */

import type { RuleDocumentation } from "../documentation.js";

export interface RuleOptions {
  readonly modules?: readonly string[];
  readonly methods?: readonly string[];
}

export type Options = readonly [RuleOptions?];

export const NO_STORAGE_IN_STATELESS_MODULES_DOCUMENTATION = {
  summary: "Disallow SQL or key/value access inside configured stateless modules; derive state from a system of record instead.",
  rationale: "Private storage in a stateless workflow creates another source of truth that can silently diverge.",
  remediation: "Read from the system of record or derive state from an artifact the workflow already produces.",
  category: "architecture",
  limitations: ["This opt-in architectural policy requires configured module paths and storage method names. Overloaded `put` requires storage-like receiver evidence; `prepare` requires SQL-shaped literal text or a conventional database receiver for dynamic text. These syntax heuristics do not prove database provenance or identify the system of record."],
  examples: [
    { id: "system-of-record", title: "Read from the system of record", outcome: "no-match", files: [{ path: "src/engineer-digest/post.ts", source: "const issues = await linear.listIssues();" }], focusPath: "src/engineer-digest/post.ts", expectedCount: 0, public: true, ruleOptions: [{ modules: ["[\\\\/]engineer-digest[\\\\/]"] }] },
    { id: "private-storage", title: "Do not write private state in a stateless module", outcome: "match", files: [{ path: "src/engineer-digest/post.ts", source: "export {}; await kv.put('digest:last', timestamp);" }], focusPath: "src/engineer-digest/post.ts", expectedCount: 1, public: true, ruleOptions: [{ modules: ["[\\\\/]engineer-digest[\\\\/]"] }] },
  ],
} as const satisfies RuleDocumentation<Options>;
