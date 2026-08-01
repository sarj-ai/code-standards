import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-dynamic-sql.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-dynamic-sql", rule, {
  valid: [
    // --- The correct shape: static statement + bound placeholder ------------
    { code: "db.prepare('select * from users where id = ?').bind(userId);" },
    { code: 'db.prepare("select * from users where id = $1").bind(userId);' },
    // A template literal with no interpolation at all is just a string.
    { code: "db.prepare(`select * from users`);" },
    // --- CONSTANT_CASE fragments are compile-time values --------------------
    { code: "db.prepare(`select ${CANDIDATE_COLS} from candidates`);" },
    { code: "db.prepare(`select * from ${TABLES.USERS} where id = ?`);" },
    { code: "db.prepare(`select ${COLS} from ${TABLE} where id = ?`);" },
    // --- Tagged templates parameterise by construction ----------------------
    { code: "const q = sql`select * from users where id = ${userId}`;" },
    { code: "await db.query(sql`select * from t where id = ${id}`);" },
    // --- Not a statement-taking method --------------------------------------
    { code: "logger.info(`user ${userId} seen`);" },
    { code: "element.setAttribute(`data-${key}`, value);" },
    { code: "cache.get(`user:${userId}`);" },
    // A computed method name we cannot resolve.
    { code: "db['prepare'](`select * from t where id = ${id}`);" },
    // --- Concatenation that is not statement building -----------------------
    // No string literal in the chain: ordinary arithmetic/among values.
    { code: "db.prepare(base + suffix);" },
    // A method call with no arguments at all.
    { code: "db.prepare();" },
    // --- Not SQL at all -----------------------------------------------------
    // `exec` is child_process's method too. Real corpus:
    // react-router/integration/helpers/playwright-fixture.ts:230 —
    // a shell command line, not a statement.
    { code: "cp.exec(`open ${this.app.serverUrl}${href}`);" },
    // react-router/scripts/changes/publish.ts:111.
    {
      code: "cp.exec(`npm view ${packageName}@${version} version`, { encoding: 'utf-8' }, cb);",
    },
    // Concatenated shell arguments are equally not SQL.
    { code: 'cp.exec("git rev-parse " + ref);' },
    // --- Custom `methods` replaces the defaults -----------------------------
    {
      code: "db.query(`select * from t where id = ${id}`);",
      options: [{ methods: ["prepare"] }],
    },
  ],
  invalid: [
    // Classic injection via template interpolation.
    {
      code: "db.prepare(`select * from users where id = '${userId}'`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    // Other default methods.
    {
      code: "db.exec(`delete from sessions where token = '${token}'`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    {
      code: "await db.query(`select * from t where slug = '${slug}'`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    // A member expression whose final property is lowercase is runtime data.
    {
      code: "db.prepare(`select * from t where id = '${input.userId}'`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    // A call result is unambiguously runtime data.
    {
      code: "db.prepare(`select * from t where id = '${getId()}'`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    // Each runtime interpolation is reported; the CONSTANT_CASE one is not, so
    // this mixed statement yields exactly one diagnostic.
    {
      code: "db.prepare(`select ${COLS} from t where id = '${userId}'`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    // Two runtime interpolations, two diagnostics.
    {
      code: "db.prepare(`select * from t where a = '${a}' and b = '${b}'`);",
      errors: [{ messageId: "dynamicSql" }, { messageId: "dynamicSql" }],
    },
    // String concatenation is the same injection in older clothes.
    {
      code: "db.prepare(\"select * from users where id = '\" + userId + \"'\");",
      errors: [{ messageId: "dynamicSql" }],
    },
    // Custom `methods` picks up a driver-specific name.
    {
      code: "db.raw(`select * from t where id = '${id}'`);",
      options: [{ methods: ["raw"] }],
      errors: [{ messageId: "dynamicSql" }],
    },
    // The "is this SQL?" gate must not open an escape hatch: `exec` on a real
    // statement still fires, and so do the DDL/upsert verbs.
    {
      code: "conn.exec(`update accounts set balance = ${amount} where id = 1`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    {
      code: "db.prepare(`insert into audit (actor) values ('${actor}')`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    {
      code: "db.exec(`drop table ${tableName}`);",
      errors: [{ messageId: "dynamicSql" }],
    },
  ],
});
