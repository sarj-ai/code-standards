import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/store-insert-requires-on-conflict.js";

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
    // --- Already an upsert, in each supported spelling. ---
    {
      code: "db.prepare(`INSERT INTO runs (id, status) VALUES (?1, ?2) ON CONFLICT(id) DO NOTHING`).run();",
    },
    {
      code: "db.prepare(`INSERT INTO runs (id) VALUES (?) ON CONFLICT (id) DO UPDATE SET seen = 1`).run();",
    },
    {
      code: "db.prepare(`INSERT INTO runs (id) VALUES (?)\n  ON CONFLICT(id)\n  DO NOTHING`).run();",
    },
    // SQLite's own idempotent insert forms.
    { code: "db.prepare(`INSERT OR IGNORE INTO runs (id) VALUES (?)`).run();" },
    { code: "db.prepare(`INSERT OR REPLACE INTO runs (id) VALUES (?)`).run();" },
    // MySQL's equivalent contract.
    {
      code: "db.query(`INSERT INTO runs (id) VALUES (?) ON DUPLICATE KEY UPDATE seen = 1`);",
    },
    // --- Not an insert write at all. ---
    { code: "db.prepare(`SELECT id, status FROM runs WHERE id = ?`).first();" },
    { code: "db.prepare(`UPDATE runs SET status = ? WHERE id = ?`).run();" },
    { code: "db.prepare(`DELETE FROM runs WHERE id = ?`).run();" },
    { code: "db.exec(`CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY)`);" },
    // Prose that merely mentions the words is not SQL.
    { code: 'log("failed to insert into the queue: values were rejected");' },
    // --- Fragment arrays are read as one statement, so the ON CONFLICT counts. ---
    {
      code: [
        "const sql = [",
        "  'INSERT INTO ratings (path, email, rating)',",
        "  'VALUES (?, ?, ?)',",
        "  'ON CONFLICT(path, email) DO UPDATE SET rating = excluded.rating',",
        "].join(' ');",
      ].join("\n"),
    },
    // --- `+` concatenation is reassembled before matching. ---
    {
      code: "const sql = 'INSERT INTO runs (id) VALUES (?) ' + 'ON CONFLICT(id) DO NOTHING';",
    },
    // --- Interpolated multi-row VALUES still sees the clause after it. ---
    {
      code: "db.prepare(`INSERT INTO runs (id, at) VALUES ${rows} ON CONFLICT(id) DO UPDATE SET at = excluded.at`).run();",
    },
    // --- Noise stripping: an ON CONFLICT inside a quoted value must NOT excuse a
    // bare insert, and a bare insert inside a comment must NOT trigger one. ---
    {
      code: "db.prepare(`-- INSERT INTO runs (id) VALUES (?)\\nSELECT id FROM runs`).all();",
    },
    // --- Test files seed fixtures against a fresh database. ---
    {
      code: "await db.prepare(`INSERT INTO runs (id) VALUES ('a')`).run();",
      filename: "/repo/test/runs.test.ts",
    },
    {
      code: "await db.prepare(`INSERT INTO runs (id) VALUES ('a')`).run();",
      filename: "/repo/src/__tests__/seed.ts",
    },
    // --- CROSS-PACKAGE PARITY with Python's SARJ018 and SQL's SARJ105
    // (`packages/python/.../store_insert_requires_on_conflict.py`,
    // `packages/sql/.../insert_requires_on_conflict.py`). All three must share
    // ONE definition of "already idempotent". A MySQL upsert used to be a false
    // positive in the other two while this rule correctly excused it. If one of
    // these fails, the three implementations have drifted again. ---
    {
      code: "db.prepare(`INSERT INTO t (a, b) VALUES (?, ?) ON CONFLICT (a) DO NOTHING`).run();",
    },
    {
      code: "db.prepare(`INSERT INTO t (a, b) VALUES (?, ?) ON DUPLICATE KEY UPDATE b = VALUES(b)`).run();",
    },
    { code: "db.prepare(`INSERT OR IGNORE INTO t (a) VALUES (?)`).run();" },
    { code: "db.prepare(`INSERT OR REPLACE INTO t (a) VALUES (?)`).run();" },
    // The write-verb gate: an `INSERT` privilege grant is not a write.
    { code: "db.prepare(`GRANT INSERT ON TABLE t TO app_role`).run();" },
    // Strict adjacency keeps English prose out. Python's `.*?` under DOTALL
    // matched `insert into ... values` across this whole sentence.
    {
      code: "const msg = 'failed to insert into the queue: values were rejected by the broker';",
    },
  ],
  invalid: [
    // `OR IGNORE`/`OR REPLACE` survive replay; `OR ABORT` does not.
    {
      code: "db.prepare(`INSERT OR ABORT INTO t (a) VALUES (?)`).run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    // The base case: a bare insert on a store write path.
    {
      code: "db.prepare(`INSERT INTO runs (id, status) VALUES (?1, ?2)`).run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    // Multi-line with a RETURNING tail — still a bare insert.
    {
      code: "db.prepare(`INSERT INTO datasets (id, memory_mb)\n  VALUES (?, ?)\n  RETURNING id, memory_mb`).first();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    // INSERT ... SELECT is a write too.
    {
      code: "db.prepare(`INSERT INTO archive (id) SELECT id FROM runs WHERE done = 1`).run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    // Interpolated column/value lists do not hide the missing clause.
    {
      code: "db.prepare(`INSERT INTO runs (${cols}) VALUES ${rows}`).run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    // An `ON CONFLICT` living inside a quoted VALUE is neutralized, so this bare
    // insert is still reported — the FP-tuning check that matters most.
    {
      code: "db.prepare(`INSERT INTO notes (id, body) VALUES (?, 'ON CONFLICT DO NOTHING')`).run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    // A commented-out clause does not excuse the write either.
    {
      code: "db.prepare(`INSERT INTO runs (id) VALUES (?)\\n-- ON CONFLICT(id) DO NOTHING`).run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    // Fragment array with no conflict clause anywhere: one report on the array.
    {
      code: [
        "const sql = [",
        "  'INSERT INTO ratings (path, email)',",
        "  'VALUES (?, ?)',",
        "].join(' ');",
      ].join("\n"),
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
    // A plain string literal argument, not a template.
    {
      code: "db.prepare('INSERT INTO runs (id) VALUES (?)').run();",
      errors: [{ messageId: "storeInsertRequiresOnConflict" }],
    },
  ],
});
