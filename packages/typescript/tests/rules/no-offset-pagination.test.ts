import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-offset-pagination.js";

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
    // --- Keyset pagination, the recommended form. ---
    {
      code: "db.prepare(`SELECT id, status FROM runs WHERE id > ? ORDER BY id LIMIT ?`).all();",
    },
    { code: "db.prepare(`SELECT id FROM runs ORDER BY created_at LIMIT ?`).all();" },
    // --- The English word with no value token after it is not the keyword. ---
    { code: 'throw new Error("offset out of range");' },
    { code: 'log("no base offset configured for this timezone");' },
    { code: "const message = `pagination offset is not supported here`;" },
    // A column literally called offset, selected rather than applied.
    { code: "db.prepare(`SELECT tz_offset FROM users WHERE id = ?`).first();" },
    // Array-index constructs put no value after OFFSET.
    { code: "db.prepare(`SELECT v FROM UNNEST(items) WITH OFFSET AS idx`).all();" },
    // --- A quoted VALUE that reads like a clause is neutralized first. ---
    {
      code: "db.prepare(`SELECT id FROM runs WHERE note = 'LIMIT 10 OFFSET 20'`).all();",
    },
    // --- A commented-out clause is not live SQL. ---
    {
      code: "db.prepare(`SELECT id FROM runs ORDER BY id LIMIT ?\\n-- OFFSET ?`).all();",
    },
    // --- Test files are out of scope. ---
    {
      code: "await db.prepare(`SELECT id FROM runs LIMIT ? OFFSET ?`).all();",
      filename: "/repo/test/runs.test.ts",
    },
  ],
  invalid: [
    // The SQLite/D1 parameter markers.
    {
      code: "db.prepare(`SELECT id, status FROM runs ORDER BY created_at LIMIT ? OFFSET ?`).all();",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    {
      code: "db.prepare(`SELECT id FROM runs ORDER BY id LIMIT ?1 OFFSET ?2`).all();",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    // A hard-coded offset is the same O(N) scan.
    {
      code: "db.prepare(`SELECT id FROM runs ORDER BY id LIMIT 50 OFFSET 500`).all();",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    // Interpolation becomes a `?` marker, so it is still caught.
    {
      code: "db.prepare(`SELECT id FROM runs ORDER BY id LIMIT ${limit} OFFSET ${page * limit}`).all();",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    // Named / positional parameter styles from other drivers.
    {
      code: "db.query(`SELECT id FROM runs ORDER BY id LIMIT :limit OFFSET :offset`);",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    {
      code: "db.query(`SELECT id FROM runs ORDER BY id LIMIT $1 OFFSET $2`);",
      errors: [{ messageId: "noOffsetPagination" }],
    },
    // A bare paginated fragment concatenated onto a base query.
    {
      code: "const sql = base + ' LIMIT ? OFFSET ?';",
      errors: [{ messageId: "noOffsetPagination" }],
    },
  ],
});
