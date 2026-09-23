import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_DYNAMIC_SQL_DOCUMENTATION } from "../../src/rules/no-dynamic-sql.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

RULE_TESTER.run("no-dynamic-sql", rule, {
  valid: [
    { name: "ignores quoted interpolation in nested PostgreSQL comments", code: "db.query(`SELECT id FROM users /* outer /* inner */ '${note}' */`);" },
    { name: "does not prescribe value bindings for quoted identifiers", code: 'db.query(`SELECT "${column}" FROM users`);' },
    { name: "ignores quoted interpolation in SQL line comments", code: "db.query(`SELECT id FROM users -- '${note}'`);" },
    { name: "ignores quoted interpolation in SQL block comments", code: "db.query(`SELECT id FROM users /* '${note}' */`);" },
    { name: "ignores quoted interpolation inside dollar strings", code: "db.query(`SELECT $$ '${note}' $$ FROM users`);" },
    { name: "does not prescribe value bindings for concatenated identifiers", code: 'db.query(\'SELECT "\' + column + \'" FROM users\');' },
    {
      name: "accepts a question-mark placeholder bound separately",
      code: NO_DYNAMIC_SQL_DOCUMENTATION.examples[0].files[0].source,
    },
    {
      name: "accepts a positional placeholder bound separately",
      code: 'db.prepare("select * from users where id = $1").bind(userId);',
    },
    {
      name: "accepts a template literal without interpolations",
      code: "db.prepare(`select * from users`);",
    },
    {
      name: "accepts a CONSTANT_CASE identifier as a static fragment",
      code: "db.prepare(`select ${CANDIDATE_COLS} from candidates`);",
    },
    {
      name: "accepts an uppercase member property as a static fragment",
      code: "db.prepare(`select * from ${TABLES.USERS} where id = ?`);",
    },
    {
      name: "accepts multiple static fragments",
      code: "db.prepare(`select ${COLS} from ${TABLE} where id = ?`);",
    },
    {
      name: "accepts a string literal expression as a static fragment",
      code: 'db.prepare(`select * from ${"users"}`);',
    },
    {
      name: "accepts a static fragment in a concatenation",
      code: 'db.prepare("select " + COLS + " from users");',
    },
    {
      name: "ignores runtime interpolation inside a SQL line comment",
      code: "db.prepare(`select id from users -- ${note}`);",
    },
    {
      name: "ignores runtime interpolation inside a SQL block comment",
      code: "db.prepare(`select id from users /* ${note} */`);",
    },
    {
      name: "ignores runtime interpolation inside a dollar string",
      code: "db.prepare(`select $$ ${note} $$ from users`);",
    },
    {
      name: "does not claim a double-quoted SQL identifier is bindable",
      code: "db.prepare(`select \"${column}\" from users`);",
    },
    {
      name: "accepts a parameterizing tagged template",
      code: "const q = sql`select * from users where id = ${userId}`;",
    },
    {
      name: "accepts a tagged template passed to an inspected method",
      code: "await db.query(sql`select * from t where id = ${id}`);",
    },
    {
      name: "ignores an uninspected method",
      code: "logger.info(`user ${userId} seen`);",
    },
    {
      name: "ignores an unrelated DOM method",
      code: "element.setAttribute(`data-${key}`, value);",
    },
    {
      name: "ignores an unrelated cache method",
      code: "cache.get(`user:${userId}`);",
    },
    {
      name: "ignores a computed method name",
      code: "db['prepare'](`select * from t where id = ${id}`);",
    },
    {
      name: "ignores concatenation without a string literal",
      code: "db.prepare(base + suffix);",
    },
    { name: "ignores a call without arguments", code: "db.prepare();" },
    {
      name: "ignores a non-SQL prepare call",
      code: "widget.prepare(`release ${version}`);",
    },
    {
      name: "ignores an interpolated shell command passed to exec",
      code: "cp.exec(`open ${this.app.serverUrl}${href}`);",
    },
    {
      name: "ignores another interpolated shell command",
      code: "cp.exec(`npm view ${packageName}@${version} version`, { encoding: 'utf-8' }, cb);",
    },
    {
      name: "ignores a concatenated shell command",
      code: 'cp.exec("git rev-parse " + ref);',
    },
    {
      name: "custom methods replace the defaults",
      code: "db.query(`select * from t where id = ${id}`);",
      options: [{ methods: ["prepare"] }],
    },
  ],
  invalid: [
    {
      name: "rejects an unquoted runtime value in prepare",
      code: "db.prepare(`select id from users where id = ${id}`);",
      errors: [{ messageId: "dynamicFragment" }],
    },
    {
      name: "rejects an unquoted runtime identifier in prepare",
      code: "db.prepare(`select * from ${tableName}`);",
      errors: [{ messageId: "dynamicFragment" }],
    },
    {
      name: "reports multiple runtime fragments without reporting a constant fragment",
      code: "db.prepare(`select ${COLS} from ${tableName} limit ${limit}`);",
      errors: [{ messageId: "dynamicFragment" }, { messageId: "dynamicFragment" }],
    },
    {
      name: "rejects a runtime member expression",
      code: "db.prepare(`select id from users where id = ${input.id}`);",
      errors: [{ messageId: "dynamicFragment" }],
    },
    {
      name: "rejects a runtime call result",
      code: "db.prepare(`select id from users where id = ${getId()}`);",
      errors: [{ messageId: "dynamicFragment" }],
    },
    {
      name: "rejects an unquoted runtime concatenation",
      code: "db.prepare('select id from users where id = ' + userId);",
      errors: [{ messageId: "dynamicFragment" }],
    },
    {
      name: "rejects an unquoted runtime fragment in a configured driver method",
      code: "db.raw(`select * from ${tableName}`);",
      options: [{ methods: ["raw"] }],
      errors: [{ messageId: "dynamicFragment" }],
    },
    { name: "recognizes a value after a quoted identifier and dollar string", code: 'db.query(`SELECT "id", $$ literal $$ FROM users WHERE name = \'${name}\'`);', errors: [{ messageId: "dynamicSql" }] },
    {
      name: "reports a runtime concatenation inside a quoted value",
      code: "db.prepare(\"select id from users where role = '\" + userId + \"'\");",
      errors: [{ messageId: "dynamicSql" }],
    },
    {
      name: "reports runtime template interpolation",
      code: NO_DYNAMIC_SQL_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "dynamicSql" }],
    },
    {
      name: "reports runtime interpolation passed to exec",
      code: "db.exec(`delete from sessions where token = '${token}'`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    {
      name: "reports runtime interpolation passed to query",
      code: "await db.query(`select * from t where slug = '${slug}'`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    {
      name: "treats a lowercase member property as runtime data",
      code: "db.prepare(`select * from t where id = '${input.userId}'`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    {
      name: "treats a call result as runtime data",
      code: "db.prepare(`select * from t where id = '${getId()}'`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    {
      name: "reports only the runtime expression in a mixed template",
      code: "db.prepare(`select ${COLS} from t where id = '${userId}'`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    {
      name: "reports every runtime interpolation",
      code: "db.prepare(`select * from t where a = '${a}' and b = '${b}'`);",
      errors: [{ messageId: "dynamicSql" }, { messageId: "dynamicSql" }],
    },
    {
      name: "reports runtime string concatenation",
      code: "db.prepare(\"select * from users where id = '\" + userId + \"'\");",
      errors: [{ messageId: "dynamicSql" }],
    },
    {
      name: "inspects a configured driver-specific method",
      code: "db.raw(`select * from t where id = '${id}'`);",
      options: [{ methods: ["raw"] }],
      errors: [{ messageId: "dynamicSql" }],
    },
    {
      name: "recognizes an update statement",
      code: "conn.exec(`update accounts set note = '${note}' where id = 1`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    {
      name: "recognizes an insert statement",
      code: "db.prepare(`insert into audit (actor) values ('${actor}')`);",
      errors: [{ messageId: "dynamicSql" }],
    },
    {
      name: "recognizes a common-table expression",
      code: "db.query(`with selected as (select * from users) select * from selected where slug = '${slug}'`);",
      errors: [{ messageId: "dynamicSql" }],
    },
  ],
});
