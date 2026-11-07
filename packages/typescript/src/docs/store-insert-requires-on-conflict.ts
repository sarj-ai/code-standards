/** @fileoverview store-insert-requires-on-conflict — the documentation and executable examples of `@sarj/store-insert-requires-on-conflict`. */

import type { RuleDocumentation } from "../documentation.js";

export const STORE_INSERT_REQUIRES_ON_CONFLICT_DOCUMENTATION = {
  summary: "Review conflict handling for embedded inserts in replay-named callables.",
  rationale: "Names such as seed, enqueue, or upsert suggest that repeated execution deserves a conflict-policy review, but do not prove a replay contract.",
  remediation: "Choose conflict handling appropriate to the schema and SQL dialect, or document why this insertion must fail on a duplicate.",
  category: "correctness",
  limitations: ["Only the nearest statically named callable is considered; top-level inserts and anonymous callbacks are excluded. Recognized conflict syntax does not prove idempotence or concurrency safety: WHERE NOT EXISTS can race, and INSERT OR REPLACE can delete an existing row. Review unique constraints and dialect semantics manually."],
  examples: [
    { id: "conflict-safe-insert", title: "Review the conflict policy for a replayed insert", outcome: "no-match", files: [{ path: "src/store.ts", source: "function seed() { db.prepare(`INSERT INTO runs (id) VALUES (?) ON CONFLICT(id) DO NOTHING`).run(); }" }], focusPath: "src/store.ts", expectedCount: 0, public: true },
    { id: "bare-insert", title: "Review a bare insert in a replay-named callable", outcome: "match", files: [{ path: "src/store.ts", source: "function seed() { db.prepare(`INSERT INTO runs (id) VALUES (?)`).run(); }" }], focusPath: "src/store.ts", expectedCount: 1, public: true },
    { id: "decoded-query", scenarioId: "native-decoded-sql", title: "Inspect native-decoded query text", outcome: "match", files: [{ path: "src/page.ts", source: "function seed(){db.query(\"INS\\u0045RT INTO runs(id,note) VALUES(4,'new')\");}" }], focusPath: "src/page.ts", expectedCount: 1, public: true },
    { id: "decoded-comment-data", scenarioId: "native-decoded-sql", title: "Ignore native-decoded comment data", outcome: "no-match", files: [{ path: "src/page.ts", source: "function seed(){db.query(\"SELECT id FROM runs /* INS\\x45RT INTO runs(id,note) VALUES(4,'new') */\");}" }], focusPath: "src/page.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
