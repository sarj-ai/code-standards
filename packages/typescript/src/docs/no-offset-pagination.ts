/** @fileoverview no-offset-pagination — the documentation and executable examples of `@sarj/no-offset-pagination`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_OFFSET_PAGINATION_DOCUMENTATION = {
  summary: "Prefer keyset pagination for embedded SQL queries using OFFSET.",
  rationale: "Offset pagination scans skipped rows and shifts page boundaries under concurrent writes.",
  remediation: "Consider a keyset cursor that preserves the query's complete ordering, tie-breakers, and filters.",
  category: "performance",
  limitations: ["A SELECT/FROM query shape or adjacent LIMIT/OFFSET fragment is required. Isolated OFFSET fragments and test files are excluded; this lexical context does not prove a database execution sink. Performance and concurrent-write behavior depend on indexes, ordering, isolation, and dialect; bounded pages and random page access can justify OFFSET."],
  examples: [
    { id: "keyset-pagination", title: "Page from a stable cursor", outcome: "no-match", files: [{ path: "src/runs.ts", source: "db.prepare(`SELECT id FROM runs WHERE id > ? ORDER BY id LIMIT ?`).all();" }], focusPath: "src/runs.ts", expectedCount: 0, public: true },
    { id: "offset-pagination", title: "Do not page by offset", outcome: "match", files: [{ path: "src/runs.ts", source: "db.query(`SELECT id FROM runs ORDER BY id LIMIT ? OFFSET ?`);" }], focusPath: "src/runs.ts", expectedCount: 1, public: true },
    { id: "decoded-query", scenarioId: "native-decoded-sql", title: "Inspect native-decoded query text", outcome: "match", files: [{ path: "src/page.ts", source: "db.query(\"SELECT id FROM runs ORDER BY id LIMIT 1 OFF\\u0053ET 1\");" }], focusPath: "src/page.ts", expectedCount: 1, public: true },
    { id: "decoded-comment-data", scenarioId: "native-decoded-sql", title: "Ignore native-decoded comment data", outcome: "no-match", files: [{ path: "src/page.ts", source: "db.query(\"SELECT id FROM runs /* OFF\\x53ET 1 */\");" }], focusPath: "src/page.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
