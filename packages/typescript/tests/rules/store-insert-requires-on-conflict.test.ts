import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { storeInsertRequiresOnConflictDocumentation } from "../../src/rules/store-insert-requires-on-conflict.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("store-insert-requires-on-conflict", rule, {
  valid: [
    { name: "accepts the documented conflict-safe insert", code: storeInsertRequiresOnConflictDocumentation.examples[0].files[0].source },
    {
      name: "allows SQLite ON CONFLICT DO NOTHING",
      code: "db.prepare(`INSERT INTO runs (id, status) VALUES (?1, ?2) ON CONFLICT(id) DO NOTHING`).run();",
    },
    {
      name: "allows SQLite ON CONFLICT DO UPDATE",
      code: "db.prepare(`INSERT INTO runs (id) VALUES (?) ON CONFLICT (id) DO UPDATE SET seen = 1`).run();",
    },
    {
      name: "allows a multiline conflict clause",
      code: "db.prepare(`INSERT INTO runs (id) VALUES (?)\n  ON CONFLICT(id)\n  DO NOTHING`).run();",
    },
    {
      name: "allows SQLite INSERT OR IGNORE",
      code: "db.prepare(`INSERT OR IGNORE INTO runs (id) VALUES (?)`).run();",
    },
    {
      name: "allows SQLite INSERT OR REPLACE",
      code: "db.prepare(`INSERT OR REPLACE INTO runs (id) VALUES (?)`).run();",
    },
    {
      name: "allows MySQL ON DUPLICATE KEY UPDATE",
      code: "db.query(`INSERT INTO runs (id) VALUES (?) ON DUPLICATE KEY UPDATE seen = 1`);",
    },
    { code: "db.prepare(`SELECT id, status FROM runs WHERE id = ?`).first();" },
    { code: "db.prepare(`UPDATE runs SET status = ? WHERE id = ?`).run();" },
    { code: "db.prepare(`DELETE FROM runs WHERE id = ?`).run();" },
    { code: "db.exec(`CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY)`);" },
    {
      name: "ignores prose with nonadjacent SQL keywords",
      code: 'log("failed to insert into the queue: values were rejected");',
    },
    {
      name: "reassembles joined SQL fragments before checking conflicts",
      code: [
        "const sql = [",
        "  'INSERT INTO ratings (path, email, rating)',",
        "  'VALUES (?, ?, ?)',",
        "  'ON CONFLICT(path, email) DO UPDATE SET rating = excluded.rating',",
        "].join(' ');",
      ].join("\n"),
    },
    {
      name: "reassembles concatenated SQL before checking conflicts",
      code: "const sql = 'INSERT INTO runs (id) VALUES (?) ' + 'ON CONFLICT(id) DO NOTHING';",
    },
    {
      name: "allows an upsert with interpolated rows",
      code: "db.prepare(`INSERT INTO runs (id, at) VALUES ${rows} ON CONFLICT(id) DO UPDATE SET at = excluded.at`).run();",
    },
    {
      name: "ignores an insert inside a line comment",
      code: "db.prepare(`-- INSERT INTO runs (id) VALUES (?)\\nSELECT id FROM runs`).all();",
    },
    {
      name: "ignores an insert inside a block comment",
      code: "db.prepare(`/* INSERT INTO runs (id) VALUES (?) */ SELECT id FROM runs`).all();",
    },
    {
      name: "does not let dashes in a value hide a real conflict clause",
      code: "db.prepare(`INSERT INTO notes (id, body) VALUES (?, 'a--b') ON CONFLICT(id) DO NOTHING`).run();",
    },
    {
      name: "allows fixture inserts in dot-test files",
      code: "await db.prepare(`INSERT INTO runs (id) VALUES ('a')`).run();",
      filename: "/repo/test/runs.test.ts",
    },
    {
      name: "allows fixture inserts under __tests__",
      code: "await db.prepare(`INSERT INTO runs (id) VALUES ('a')`).run();",
      filename: "/repo/src/__tests__/seed.ts",
    },
    {
      code: "db.prepare(`INSERT INTO t (a, b) VALUES (?, ?) ON CONFLICT (a) DO NOTHING`).run();",
    },
    {
      code: "db.prepare(`INSERT INTO t (a, b) VALUES (?, ?) ON DUPLICATE KEY UPDATE b = VALUES(b)`).run();",
    },
    { code: "db.prepare(`INSERT OR IGNORE INTO t (a) VALUES (?)`).run();" },
    { code: "db.prepare(`INSERT OR REPLACE INTO t (a) VALUES (?)`).run();" },
    {
      name: "ignores an INSERT privilege grant",
      code: "db.prepare(`GRANT INSERT ON TABLE t TO app_role`).run();",
    },
    {
      name: "ignores prose spanning insert, into, and values",
      code: "const msg = 'failed to insert into the queue: values were rejected by the broker';",
    },
  ],
  invalid: [
    { name: "reports the documented bare insert", code: storeInsertRequiresOnConflictDocumentation.examples[1].files[0].source, errors: [{ messageId: "storeInsertRequiresOnConflict" }] },
    {
      name: "reports SQLite INSERT OR ABORT",
      code: "db.prepare(`INSERT OR ABORT INTO t (a) VALUES (?)`).run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    {
      name: "reports a bare VALUES insert",
      code: "db.prepare(`INSERT INTO runs (id, status) VALUES (?1, ?2)`).run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    {
      name: "reports a bare insert with a RETURNING tail",
      code: "db.prepare(`INSERT INTO datasets (id, memory_mb)\n  VALUES (?, ?)\n  RETURNING id, memory_mb`).first();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    {
      name: "reports a bare INSERT SELECT",
      code: "db.prepare(`INSERT INTO archive (id) SELECT id FROM runs WHERE done = 1`).run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    {
      name: "reports interpolated column and value lists",
      code: "db.prepare(`INSERT INTO runs (${cols}) VALUES ${rows}`).run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    {
      name: "does not accept ON CONFLICT inside a quoted value",
      code: "db.prepare(`INSERT INTO notes (id, body) VALUES (?, 'ON CONFLICT DO NOTHING')`).run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    {
      name: "does not accept a conflict clause inside a line comment",
      code: "db.prepare(`INSERT INTO runs (id) VALUES (?)\\n-- ON CONFLICT(id) DO NOTHING`).run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    {
      name: "does not accept a conflict clause inside a block comment",
      code: "db.prepare(`INSERT INTO runs (id) VALUES (?) /* ON CONFLICT(id) DO NOTHING */`).run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    {
      name: "reports a joined fragment array once",
      code: [
        "const sql = [",
        "  'INSERT INTO ratings (path, email)',",
        "  'VALUES (?, ?)',",
        "].join(' ');",
      ].join("\n"),
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    {
      name: "reports a plain string literal",
      code: "db.prepare('INSERT INTO runs (id) VALUES (?)').run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    {
      name: "reports a bare DEFAULT VALUES insert",
      code: "db.prepare(`INSERT INTO runs DEFAULT VALUES`).run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    {
      name: "reports a bare tagged template insert",
      code: "sql`INSERT INTO runs (id) VALUES (${id})`;",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
  ],
});
