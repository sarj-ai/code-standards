import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-select-star.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-select-star", rule, {
  valid: [
    // --- Explicit projections. ---
    { code: "db.prepare(`SELECT id, status, created_at FROM runs WHERE id = ?`).first();" },
    { code: "db.prepare(`SELECT r.id, r.status FROM runs r JOIN jobs j ON j.id = r.job_id`).all();" },
    // --- The star is a function argument, not a projection. ---
    { code: "db.prepare(`SELECT COUNT(*) AS n FROM runs`).first();" },
    { code: "db.prepare(`SELECT COUNT( * ) AS n FROM runs WHERE status = ?`).first();" },
    // --- Arithmetic, not a projection: an operand follows the star. ---
    { code: "db.prepare(`SELECT price * quantity AS total FROM line_items`).all();" },
    // --- EXISTS subqueries never use their projection. ---
    {
      code: "db.prepare(`SELECT id FROM runs r WHERE EXISTS (SELECT * FROM jobs j WHERE j.run_id = r.id)`).all();",
    },
    // --- A quoted `'*'` value is neutralized before the scan. ---
    { code: "db.prepare(`SELECT id FROM runs WHERE glob = '*' AND owner = ?`).all();" },
    { code: "db.prepare(`SELECT id FROM acl WHERE scope = 'read:*' AND owner = ?`).all();" },
    // --- Prose that merely contains the words is not a query. ---
    { code: 'log("select the * you want to copy from the list above");' },
    // --- Not a query shape at all (no FROM). ---
    { code: "const glob = `SELECT *`;" },
    // --- Commented-out SQL is not live. ---
    { code: "db.prepare(`-- SELECT * FROM runs\\nSELECT id FROM runs`).all();" },
    // --- Test files may assert over whole fixture rows. ---
    {
      code: "await db.prepare(`SELECT * FROM runs`).all();",
      filename: "/repo/test/runs.test.ts",
    },
  ],
  invalid: [
    {
      code: "db.prepare(`SELECT * FROM runs WHERE id = ?`).first();",
      errors: [{ messageId: "noSelectStar" }],
    },
    // Qualified star.
    {
      code: "db.prepare(`SELECT r.* FROM runs r JOIN jobs j ON j.id = r.job_id`).all();",
      errors: [{ messageId: "noSelectStar" }],
    },
    // Star mixed into an otherwise explicit projection.
    {
      code: "db.prepare(`SELECT id, * FROM runs`).all();",
      errors: [{ messageId: "noSelectStar" }],
    },
    // Multi-line and lower-case spellings.
    {
      code: "db.prepare(`select *\n  from runs\n  where status = ?`).all();",
      errors: [{ messageId: "noSelectStar" }],
    },
    // A real star alongside a legitimate COUNT(*) still fires once.
    {
      code: "db.prepare(`SELECT *, COUNT(*) OVER () AS total FROM runs`).all();",
      errors: [{ messageId: "noSelectStar" }],
    },
    // Plain string literal, not a template.
    {
      code: "db.prepare('SELECT * FROM runs').all();",
      errors: [{ messageId: "noSelectStar" }],
    },
  ],
});
