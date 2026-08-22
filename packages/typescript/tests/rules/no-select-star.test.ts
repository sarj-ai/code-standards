import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_SELECT_STAR_DOCUMENTATION } from "../../src/rules/no-select-star.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

RULE_TESTER.run("no-select-star", rule, {
  valid: [
    { name: "accepts the documented projection", code: NO_SELECT_STAR_DOCUMENTATION.examples[0].files[0].source },
    {
      name: "allows explicit projections",
      code: "db.prepare(`SELECT id, status, created_at FROM runs WHERE id = ?`).first();",
    },
    {
      name: "allows qualified explicit projections",
      code: "db.prepare(`SELECT r.id, r.status FROM runs r JOIN jobs j ON j.id = r.job_id`).all();",
    },
    { name: "allows COUNT star arguments", code: "db.prepare(`SELECT COUNT(*) AS n FROM runs`).first();" },
    {
      name: "allows spaced function star arguments",
      code: "db.prepare(`SELECT COUNT( * ) AS n FROM runs WHERE status = ?`).first();",
    },
    {
      name: "allows non-COUNT function star arguments",
      code: "db.prepare(`SELECT row_tally(*) AS n FROM runs`).first();",
    },
    {
      name: "allows multiplication in a projection",
      code: "db.prepare(`SELECT price * quantity AS total FROM line_items`).all();",
    },
    {
      name: "allows an unused star projection inside EXISTS",
      code: "db.prepare(`SELECT id FROM runs r WHERE EXISTS (SELECT * FROM jobs j WHERE j.run_id = r.id)`).all();",
    },
    {
      name: "ignores a quoted star in a projection",
      code: "db.prepare(`SELECT '*' AS glob FROM patterns`).all();",
    },
    {
      name: "ignores a quoted star in a predicate",
      code: "db.prepare(`SELECT id FROM runs WHERE glob = '*' AND owner = ?`).all();",
    },
    {
      name: "ignores a star embedded in a quoted value",
      code: "db.prepare(`SELECT id FROM acl WHERE scope = 'read:*' AND owner = ?`).all();",
    },
    {
      name: "ignores prose containing SELECT, star, and FROM",
      code: 'log("select the * you want to copy from the list above");',
    },
    { name: "requires a complete SELECT FROM shape", code: "const glob = `SELECT *`;" },
    {
      name: "ignores SELECT star inside a line comment",
      code: "db.prepare(`-- SELECT * FROM runs\\nSELECT id FROM runs`).all();",
    },
    {
      name: "ignores SELECT star inside a block comment",
      code: "db.prepare(`/* SELECT * FROM runs */ SELECT id FROM runs`).all();",
    },
    {
      name: "exempts test files",
      code: "await db.prepare(`SELECT * FROM runs`).all();",
      filename: "/repo/test/runs.test.ts",
    },
  ],
  invalid: [
    { name: "reports the documented wildcard", code: NO_SELECT_STAR_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "noSelectStar" }] },
    {
      name: "rejects a bare projection star",
      code: "db.prepare(`SELECT * FROM runs WHERE id = ?`).first();",
      errors: [{ messageId: "noSelectStar" }],
    },
    {
      name: "rejects a qualified projection star",
      code: "db.prepare(`SELECT r.* FROM runs r JOIN jobs j ON j.id = r.job_id`).all();",
      errors: [{ messageId: "noSelectStar" }],
    },
    {
      name: "rejects a multiply-qualified projection star",
      code: "db.prepare(`SELECT main.runs.* FROM main.runs`).all();",
      errors: [{ messageId: "noSelectStar" }],
    },
    {
      name: "rejects a star mixed with explicit projections",
      code: "db.prepare(`SELECT id, * FROM runs`).all();",
      errors: [{ messageId: "noSelectStar" }],
    },
    {
      name: "rejects multiline lowercase SELECT star",
      code: "db.prepare(`select *\n  from runs\n  where status = ?`).all();",
      errors: [{ messageId: "noSelectStar" }],
    },
    {
      name: "reports once when a projection star accompanies COUNT star",
      code: "db.prepare(`SELECT *, COUNT(*) OVER () AS total FROM runs`).all();",
      errors: [{ messageId: "noSelectStar" }],
    },
    {
      name: "checks plain string literals",
      code: "db.prepare('SELECT * FROM runs').all();",
      errors: [{ messageId: "noSelectStar" }],
    },
    {
      name: "checks concatenated static fragments",
      code: "db.prepare('SELECT ' + '* FROM runs').all();",
      errors: [{ messageId: "noSelectStar" }],
    },
    {
      name: "checks joined static fragment arrays",
      code: "db.prepare(['SELECT *', 'FROM runs'].join(' ')).all();",
      errors: [{ messageId: "noSelectStar" }],
    },
    {
      name: "checks tagged templates",
      code: "const query = sql`SELECT * FROM runs`;",
      errors: [{ messageId: "noSelectStar" }],
    },
    {
      name: "checks templates with a dynamic table",
      code: "const query = `SELECT * FROM ${table}`;",
      errors: [{ messageId: "noSelectStar" }],
    },
  ],
});
