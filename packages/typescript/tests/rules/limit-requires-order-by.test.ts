import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/limit-requires-order-by.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;

const ruleTester = new RuleTester({ languageOptions: { parser: tsParser } });

ruleTester.run("limit-requires-order-by", rule, {
  valid: [
    { code: "db.prepare(`SELECT id FROM run ORDER BY created_at, id LIMIT ?`).all();" },
    { code: "db.prepare(`SELECT id FROM run`).all();" },
    { code: "db.prepare(`SELECT note FROM run WHERE note = 'LIMIT 10'`).all();" },
    { code: "const example = `SELECT id FROM run LIMIT 10`;" },
    { code: "const sampleQuery = sqlText; sampleQuery(`SELECT id FROM run LIMIT 10`);" },
    { code: "db.prepare(`SELECT id FROM run LIMIT ?`).all();", filename: "/repo/run.test.ts" },
  ],
  invalid: [
    {
      code: "db.prepare(`SELECT id FROM run LIMIT 1`).first();",
      errors: [{ messageId: "limitRequiresOrderBy" }],
    },
    {
      code: "db.prepare(`SELECT id FROM run LIMIT ?`).all();",
      errors: [{ messageId: "limitRequiresOrderBy" }],
    },
    {
      code: "db.prepare(`SELECT id FROM run WHERE org_id = ${orgId} LIMIT ${limit}`).all();",
      errors: [{ messageId: "limitRequiresOrderBy" }],
    },
    {
      code: "db.prepare(`WITH x AS (SELECT id FROM run ORDER BY id LIMIT 5) SELECT id FROM x LIMIT 2`).all();",
      errors: [{ messageId: "limitRequiresOrderBy" }],
    },
    {
      code: "const query = sql`SELECT id FROM run LIMIT 10`;",
      errors: [{ messageId: "limitRequiresOrderBy" }],
    },
    {
      code: "client.query({ text: `SELECT id FROM run LIMIT 10`, values: [] });",
      errors: [{ messageId: "limitRequiresOrderBy" }],
    },
    {
      code: "prisma.$queryRaw`SELECT id FROM run LIMIT 10`;",
      errors: [{ messageId: "limitRequiresOrderBy" }],
    },
    {
      code: "db.prepare(`SELECT id, (SELECT COUNT(*) FROM event) FROM run LIMIT 10`).all();",
      errors: [{ messageId: "limitRequiresOrderBy" }],
    },
    {
      code: "db.prepare(`SELECT id FROM run WHERE status = 'queued' LIMIT 1`).first();",
      errors: [{ messageId: "limitRequiresOrderBy" }],
    },
    {
      code: "db.prepare(`SELECT COUNT(*) OVER (), id FROM run LIMIT 10`).all();",
      errors: [{ messageId: "limitRequiresOrderBy" }],
    },
  ],
});
