// vitest: shared-module-graph
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
    ...[String.raw`SELECT 'it\'s SELECT * FROM hidden' AS message FROM visible`, String.raw`SELECT "it\"s SELECT * FROM hidden" AS message FROM visible`].map((sql) => ({
      name: `keeps ordinary dialect escape data masked: ${sql}`,
      code: `db.query(${JSON.stringify(sql)});`,
    })),
    ...["SELECT [SELECT EXISTS(SELECT id FROM a), * FROM b] FROM entries", "SELECT [`t`.* EXCEPT(x)] FROM entries", "SELECT `SELECT EXISTS(SELECT id FROM a), * FROM b` FROM entries"].map((sql) => ({
      name: `retains conservative ambiguous-quote handling: ${sql}`,
      code: `db.query(${JSON.stringify(sql)});`,
    })),
    ...["SELECT t.[*] FROM entries AS t", "SELECT t. [*] FROM entries AS t", "SELECT t.[a]]* FROM bogus] FROM entries AS t"].map((sql) => ({
      name: `keeps a qualified bracket identifier opaque: ${sql}`,
      code: `db.query(${JSON.stringify(sql)});`,
    })),
    ...["**", "@*", "*?", "~*"].map((operator) => ({
      name: `keeps the custom prefix operator ${operator} intact`,
      code: `db.query("SELECT ${operator}amount FROM invoices");`,
    })),
    { name: "keeps quoted arithmetic operands opaque", code: 'db.query(\'SELECT "units" * "price" FROM entries\');' },
    { name: "keeps all redundant EXISTS parentheses exempt", code: 'db.query("SELECT EXISTS((SELECT * FROM entries))");' },
    { name: "keeps a UNION within EXISTS exempt", code: 'db.query("SELECT EXISTS(SELECT * FROM a UNION SELECT * FROM b)");' },
    { name: "does not mistake a masked column's arithmetic for a wildcard", code: 'db.query(\'SELECT "units" * 2 FROM runs\');' },
    { name: "does not mistake a masked DISTINCT column's arithmetic for a wildcard", code: 'db.query(\'SELECT DISTINCT "units" * 2 FROM runs\');' },
    { name: "does not project a function's qualified row argument", code: "db.query('SELECT COUNT(r.*) FROM runs r');" },
    { name: "does not retain a completed scalar subquery's scope", code: "db.query('SELECT (SELECT 1), COUNT(r.*), EXTRACT(year FROM created_at) FROM runs r');" },
    { name: "keeps wildcard text inside an escaped PostgreSQL value", code: `db.query(${JSON.stringify(String.raw`SELECT E'it\'s SELECT * FROM hidden' AS message FROM visible`)});` },
    { name: "keeps wildcard text inside a Unicode dollar string", code: 'db.query("SELECT $текст$ SELECT * FROM hidden$текст$ AS message FROM visible");' },
    { name: "accepts a wrapped explicit projection", code: 'db.query(("SEL" as string) + ("ECT id FROM users" satisfies string));' },
    { name: "does not treat an unused join separator as SQL", code: "const note = ['ready'].join('SELECT * FROM users');" },
    { name: "abstains from joined fragments with an unknown separator", code: "db.query(['SELECT * FROM users', 'WHERE id = 1'].join(separator));" },
    { name: "ignores stars in PostgreSQL dollar strings", code: "db.query(`SELECT $$ * FROM $$`);" },
    { name: "ignores stars in tagged dollar strings", code: "db.query(`SELECT $body$ * FROM $body$`);" },
    { name: "preserves Unicode offsets while masking SQL values", code: "db.query(`SELECT '😀' AS emoji, '*' FROM users`);" },
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
    { name: "does not infer a query from reversed keywords", code: 'log("FROM entries SELECT *");' },
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
    { name: "reports an outer wildcard after EXISTS without ambiguous quoting", code: 'db.query("SELECT EXISTS(SELECT id FROM a), * FROM b");', errors: [{ messageId: "noSelectStar" }] },
    { name: "retains a real wildcard in an array subquery", code: 'db.query("SELECT ARRAY[(SELECT * FROM entries)] FROM wrapper");', errors: [{ messageId: "noSelectStar" }] },
    { name: "retains a quoted qualifier without surrounding spaces", code: 'db.query(\'SELECT"entries".*FROM entries\');', errors: [{ messageId: "noSelectStar" }] },
    { name: "retains the outer wildcard after wrapped EXISTS", code: 'db.query("SELECT EXISTS((SELECT * FROM jobs)), * FROM runs");', errors: [{ messageId: "noSelectStar" }] },
    { name: "ends SQL comments at a carriage return", code: `db.query(${JSON.stringify("-- comment\rSELECT * FROM entries")});`, errors: [{ messageId: "noSelectStar" }] },
    { name: "finds the outer wildcard after an EXISTS projection", code: "db.query('SELECT EXISTS(SELECT * FROM jobs), * FROM runs');", errors: [{ messageId: "noSelectStar" }] },
    { name: "finds a live wildcard after an escaped PostgreSQL value", code: `db.query(${JSON.stringify(String.raw`SELECT E'it\'s fine', * FROM visible`)});`, errors: [{ messageId: "noSelectStar" }] },
    { name: "reconstructs a wildcard through erased SQL fragments", code: 'db.query(("SEL" as string) + ("ECT * FROM users" satisfies string));', errors: [{ messageId: "noSelectStar" }] },
    { name: "inspects SQL reconstructed with an empty join separator", code: "db.query(['SEL', 'ECT * FROM users'].join(''));", errors: [{ messageId: "noSelectStar" }] },
    { name: "keeps executed queries inside outer template substitutions", code: 'logger.info(`value ${db.query("SELECT * FROM users")}`);', errors: [{ messageId: "noSelectStar" }] },
    { name: "retains a wildcard following a dollar-quoted literal", code: "db.query(`SELECT $$ literal $$, * FROM users`);", errors: [{ messageId: "noSelectStar" }] },
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


RULE_TESTER.run("no-select-star native-decoded SQL", rule, {
  valid: [
    { name: "native escaped-comment", code: "db.query(\"SEL\\x45CT id FROM runs /* SELECT * FROM runs */\");" },
    { name: "native escaped-value", code: "db.query(\"SEL\\x45CT id FROM runs WHERE note = 'SELECT'\");" },
    { name: "native escaped-prose", code: "db.query(\"Invalid SEL\\x45CT value\");" },
    { name: "native safe-query", code: "db.query(\"SELECT id FROM runs\");" },
  ],
  invalid: [
    { name: "native plain", code: "db.query(\"SELECT * FROM runs\");", errors: [{ messageId: "noSelectStar" }] },
    { name: "native unicode-four", code: "db.query(\"SEL\\u0045CT * FROM runs\");", errors: [{ messageId: "noSelectStar" }] },
    { name: "native unicode-codepoint", code: "db.query(\"SEL\\u{45}CT * FROM runs\");", errors: [{ messageId: "noSelectStar" }] },
    { name: "native hex", code: "db.query(\"SEL\\x45CT * FROM runs\");", errors: [{ messageId: "noSelectStar" }] },
    { name: "native concatenated", code: "db.query(\"SEL\"+\"ECT * FROM runs\");", errors: [{ messageId: "noSelectStar" }] },
    { name: "native joined", code: "db.query([\"SEL\"+\"ECT * FROM runs\"].join(\" \"));", errors: [{ messageId: "noSelectStar" }] },
  ],
});
