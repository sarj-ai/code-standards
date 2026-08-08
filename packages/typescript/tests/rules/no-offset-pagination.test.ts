import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { noOffsetPaginationDocumentation } from "../../src/rules/no-offset-pagination.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-offset-pagination", rule, {
  valid: [
    { name: "accepts the documented keyset query", code: noOffsetPaginationDocumentation.examples[0].files[0].source },
    {
      name: "allows stable keyset pagination",
      code: "db.prepare(`SELECT id, status FROM runs WHERE id > ? ORDER BY id LIMIT ?`).all();",
    },
    {
      name: "allows a bounded query without an offset",
      code: "db.prepare(`SELECT id FROM runs ORDER BY created_at LIMIT ?`).all();",
    },
    { name: "allows offset in an error message", code: 'throw new Error("offset out of range");' },
    { name: "allows offset in logged prose", code: 'log("no base offset configured for this timezone");' },
    {
      name: "allows offset in template prose",
      code: "const message = `pagination offset is not supported here`;",
    },
    { name: "allows an object key named offset", code: "const page = { offset: 20 };" },
    {
      name: "allows identifiers containing offset",
      code: "db.prepare(`SELECT tz_offset FROM users WHERE id = ?`).first();",
    },
    {
      name: "allows BigQuery array offsets",
      code: "db.prepare(`SELECT v FROM UNNEST(items) WITH OFFSET AS idx`).all();",
    },
    {
      name: "ignores offset clauses inside SQL string values",
      code: "db.prepare(`SELECT id FROM runs WHERE note = 'LIMIT 10 OFFSET 20'`).all();",
    },
    {
      name: "ignores offset clauses inside quoted SQL identifiers",
      code: 'db.prepare(`SELECT "OFFSET 20" FROM runs`).all();',
    },
    {
      name: "ignores offset clauses inside line comments",
      code: "db.prepare(`SELECT id FROM runs ORDER BY id LIMIT ?\\n-- OFFSET ?`).all();",
    },
    {
      name: "ignores offset clauses inside block comments",
      code: "db.prepare(`SELECT id FROM runs /* LIMIT 10 OFFSET 20 */ ORDER BY id`).all();",
    },
    {
      name: "exempts test files",
      code: "await db.prepare(`SELECT id FROM runs LIMIT ? OFFSET ?`).all();",
      filename: "/repo/test/runs.test.ts",
    },
    {
      name: "allows a migration adding an offset column",
      code: "db.prepare(`ALTER TABLE batch ADD COLUMN offset INTEGER NOT NULL DEFAULT 0`).run();",
    },
    {
      name: "allows a schema defining an offset column",
      code: "db.prepare(`CREATE TABLE t (id BIGINT, offset INTEGER)`).run();",
    },
    {
      name: "allows aliased BigQuery array offsets",
      code: "db.query(`SELECT x, i FROM UNNEST(arr) AS x WITH OFFSET AS i`);",
    },
  ],
  invalid: [
    { name: "reports the documented offset query", code: noOffsetPaginationDocumentation.examples[1].files[0].source, errors: [{ messageId: "noOffsetPagination" }] },
    {
      name: "rejects SQLite qmark offset pagination",
      code: "db.query(`SELECT id FROM runs ORDER BY id LIMIT ? OFFSET ?`);",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    {
      name: "rejects numbered SQLite qmark offset pagination",
      code: "db.query(`SELECT id FROM runs ORDER BY id LIMIT ?1 OFFSET ?2`);",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    {
      name: "rejects at-named offset pagination",
      code: "db.query(`SELECT id FROM runs ORDER BY id LIMIT @n OFFSET @off`);",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    {
      name: "rejects pyformat offset pagination",
      code: "db.query(`SELECT id FROM runs ORDER BY id LIMIT %s OFFSET %s`);",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    {
      name: "rejects named pyformat offset pagination",
      code: "db.query(`SELECT id FROM runs ORDER BY id LIMIT %(n)s OFFSET %(off)s`);",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    {
      name: "rejects a literal numeric offset",
      code: "db.prepare(`SELECT id FROM runs ORDER BY id LIMIT 50 OFFSET 500`).all();",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    {
      name: "rejects an interpolated offset",
      code: "db.prepare(`SELECT id FROM runs ORDER BY id LIMIT ${limit} OFFSET ${page * limit}`).all();",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    {
      name: "rejects colon-named offset pagination",
      code: "db.query(`SELECT id FROM runs ORDER BY id LIMIT :limit OFFSET :offset`);",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    {
      name: "rejects dollar-numbered offset pagination",
      code: "db.query(`SELECT id FROM runs ORDER BY id LIMIT $1 OFFSET $2`);",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    {
      name: "rejects an offset fragment appended to a dynamic base",
      code: "const sql = base + ' LIMIT ? OFFSET ?';",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    {
      name: "rejects statically concatenated offset pagination",
      code: "const sql = 'SELECT id FROM runs ORDER BY id' + ' LIMIT ? OFFSET ?';",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    {
      name: "rejects offset pagination in a joined fragment array",
      code: "const sql = ['SELECT id FROM runs', 'ORDER BY id', 'LIMIT ? OFFSET ?'].join(' ');",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    {
      name: "rejects offset pagination in a tagged template",
      code: "const sql = query`SELECT id FROM runs ORDER BY id LIMIT ? OFFSET ?`;",
      errors: [{ messageId: "noOffsetPagination" }],
    },
  ],
});
