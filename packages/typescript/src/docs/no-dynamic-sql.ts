/** @fileoverview no-dynamic-sql — the documentation and executable examples of `@sarj/no-dynamic-sql`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_DYNAMIC_SQL_DOCUMENTATION = {
  summary: "Disallow runtime values and fragments interpolated into SQL passed to statement-execution methods.",
  rationale:
    "Embedding runtime values or fragments in SQL bypasses driver parameterization or an explicit allowlist and can introduce injection defects or unstable query plans.",
  remediation: "Bind data values through SQL placeholders. Select non-bindable identifiers or clauses from fixed, reviewed fragments instead of interpolating runtime text.",
  category: "security",
  limitations: [
    "Template and concatenation fragments are inspected at recognized execution calls, including runtime pieces surrounded by literal text inside a quoted value. Double-quoted identifiers, comments, and dollar strings are excluded; this is not a general SQL injection detector.",
    "Literal fragments, legacy uppercase fragment names, and parameterizing tagged templates are exempt; uppercase spelling does not prove a value is static.",
    "The bounded lexer recognizes doubled quotes, comments, and PostgreSQL dollar strings; dialect-specific escape modes and SQL generated through other APIs require separate security review.",
  ],
  examples: [
    {
      id: "bound-sql-parameter",
      title: "A runtime value is bound separately",
      outcome: "no-match",
      files: [{ path: "src/users.ts", source: "db.prepare('select * from users where id = ?').bind(userId);" }],
      focusPath: "src/users.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "interpolated-sql-value",
      title: "A runtime value is interpolated into SQL",
      outcome: "match",
      files: [{ path: "src/users.ts", source: "db.prepare(`select * from users where id = '${userId}'`);" }],
      focusPath: "src/users.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "bound-unquoted-value",
      scenarioId: "unquoted",
      title: "An unquoted runtime value is bound separately",
      outcome: "no-match",
      files: [{ path: "src/users.ts", source: "db.prepare('select id from users where id = ?').bind(userId);" }],
      focusPath: "src/users.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "unquoted-runtime-fragment",
      scenarioId: "unquoted",
      title: "A runtime fragment is interpolated into SQL",
      outcome: "match",
      files: [{ path: "src/users.ts", source: "db.prepare(`select id from users where id = ${userId}`);" }],
      focusPath: "src/users.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
