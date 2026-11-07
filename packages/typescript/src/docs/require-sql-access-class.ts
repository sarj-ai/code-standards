/** @fileoverview require-sql-access-class — the documentation and executable examples of `@sarj/require-sql-access-class`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_SQL_ACCESS_CLASS_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Keep SQL reads and writes inside a class that receives its database dependency.",
  rationale:
    "An injected repository class is the preferred ownership boundary for database access under this architectural policy; free functions can also express explicit dependencies.",
  remediation:
    "Move the query into a repository or store class and inject the pool, connection, transaction, or typed database binding through its constructor.",
  category: "architecture",
  limitations: [
    "The rule recognizes conventional database receiver names, Cloudflare DB bindings, direct pool.query calls, explicit query-builder terminals, and Prisma-style model delegates; unusually named or heavily aliased clients require architectural review.",
    "Query construction without a recognized execution terminal is intentionally not reported.",
    "Stable local Map, WeakMap, and URLSearchParams instances are excluded. Other conventional receiver names are heuristics, not proof of a database API.",
    "Constructor injection inherited from a base class or transformed through a wrapper is not inferred by this syntax-only rule.",
  ],
  examples: [
    {
      id: "injected-repository",
      title: "Own queries in an injected repository",
      outcome: "no-match",
      files: [
        {
          path: "src/user-repository.ts",
          source:
            "export class UserRepository { constructor(private readonly db: Database.Database) {} find(id: string) { return this.db.prepare('SELECT id FROM user WHERE id = ?').get(id); } }",
        },
      ],
      focusPath: "src/user-repository.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "free-query",
      title: "Do not execute SQL in a free function",
      outcome: "match",
      files: [
        {
          path: "src/users.ts",
          source:
            "export function find(database: Database.Database, id: string) { return database.prepare('SELECT id FROM user WHERE id = ?').get(id); }",
        },
      ],
      focusPath: "src/users.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
