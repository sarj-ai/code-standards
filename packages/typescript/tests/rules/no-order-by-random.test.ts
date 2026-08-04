import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-order-by-random.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;

const ruleTester = new RuleTester({ languageOptions: { parser: tsParser } });

ruleTester.run("no-order-by-random", rule, {
  valid: [
    { code: "db.prepare(`SELECT id FROM run ORDER BY sample_key LIMIT 1`).first();" },
    { code: "db.prepare(`SELECT random_value FROM run ORDER BY random_value`).all();" },
    { code: "const example = `SELECT id FROM run ORDER BY RANDOM()`;" },
    { code: "db.prepare(`SELECT id FROM run ORDER BY RANDOM()`).all();", filename: "/repo/run.test.ts" },
  ],
  invalid: [
    {
      code: "db.prepare(`SELECT id FROM run ORDER BY RANDOM() LIMIT 1`).first();",
      errors: [{ messageId: "noOrderByRandom" }],
    },
    {
      code: "db.prepare(`SELECT id FROM run ORDER BY rand() LIMIT 1`).first();",
      errors: [{ messageId: "noOrderByRandom" }],
    },
    {
      code: "db.prepare(`SELECT id FROM run ORDER BY org_id, RANDOM() LIMIT 1`).first();",
      errors: [{ messageId: "noOrderByRandom" }],
    },
  ],
});
