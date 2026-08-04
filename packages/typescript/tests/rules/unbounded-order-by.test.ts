import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/unbounded-order-by.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;

const ruleTester = new RuleTester({ languageOptions: { parser: tsParser } });

ruleTester.run("unbounded-order-by", rule, {
  valid: [
    { code: "db.prepare(`SELECT id FROM run ORDER BY created_at LIMIT 50`).all();" },
    { code: "db.query(`SELECT id FROM run ORDER BY created_at LIMIT 2 BY org_id LIMIT 50`);" },
    { code: "db.prepare(`SELECT array_agg(id ORDER BY created_at) FROM run`).first();" },
    { code: "db.prepare(`SELECT id FROM run`).all();" },
    { code: "db.prepare(`SELECT id FROM run ORDER BY id FOR UPDATE`).all();" },
    { code: "const example = `SELECT id FROM run ORDER BY id`;" },
    { code: "db.prepare(`SELECT id FROM run ORDER BY id`).all();", filename: "/repo/run.test.ts" },
  ],
  invalid: [
    {
      code: "db.prepare(`SELECT id FROM run ORDER BY created_at`).all();",
      errors: [{ messageId: "unboundedOrderBy" }],
    },
    {
      code: "db.prepare(`SELECT id FROM run WHERE org_id = ${orgId} ORDER BY created_at, id`).all();",
      errors: [{ messageId: "unboundedOrderBy" }],
    },
    {
      code: "const query = sql`SELECT id FROM run ORDER BY created_at`;",
      errors: [{ messageId: "unboundedOrderBy" }],
    },
    {
      code: "db.query(`SELECT id FROM run ORDER BY created_at LIMIT 2 BY org_id`);",
      errors: [{ messageId: "unboundedOrderBy" }],
    },
    {
      code: "db.query(`SELECT id FROM run ORDER BY created_at LIMIT 5, 2 BY org_id`);",
      errors: [{ messageId: "unboundedOrderBy" }],
    },
    {
      code: "db.query(`SELECT id FROM run ORDER BY created_at LIMIT ALL`);",
      errors: [{ messageId: "unboundedOrderBy" }],
    },
    {
      code: "db.query(`SELECT id FROM run ORDER BY created_at LIMIT NULL`);",
      errors: [{ messageId: "unboundedOrderBy" }],
    },
  ],
});
