/** @fileoverview prefer-node-fs-promises — the documentation and executable examples of `@sarj/prefer-node-fs-promises`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_NODE_FS_PROMISES_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Prefer promise-based Node.js filesystem APIs over synchronous calls in production modules.",
  rationale: "Synchronous filesystem work blocks the event loop and can stall unrelated daemon, server, and worker tasks.",
  remediation: "Import the promise API from node:fs/promises and await it; use FileHandle.sync only where a documented durability boundary requires it.",
  category: "performance",
  limitations: [
    "Tests and generated files are excluded.",
    "This recommendation applies to Node-compatible runtimes. Changing a synchronous API to a promise changes its caller contract; review startup-only work and APIs that require synchronous execution rather than mechanically adding await.",
    "ESLint rule implementations under src/rules are excluded because visitor creation and execution are synchronous by contract.",
    "Only statically identifiable node:fs loads are inspected; filesystem objects passed through arbitrary functions or assignments require type-aware analysis.",
  ],
  examples: [
    { id: "async-read", title: "Use the promise API", outcome: "no-match", files: [{ path: "src/store.ts", source: "import { readFile } from 'node:fs/promises'; export async function load(path: string) { return readFile(path, 'utf8'); }" }], focusPath: "src/store.ts", expectedCount: 0, public: true },
    { id: "sync-read", title: "Do not block on a synchronous read", outcome: "match", files: [{ path: "src/store.ts", source: "import { readFileSync } from 'node:fs'; export function load(path: string) { return readFileSync(path, 'utf8'); }" }], focusPath: "src/store.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
