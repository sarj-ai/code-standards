import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import { expect, it } from "vitest";

import rule from "../src/rules/no-select-star.js";

const QUERY = 'SELECT * FROM (VALUES (1, 2)) AS "authored"("a", "b")';

function apply(source: string, filename = "src/literal-rows.ts"): ReturnType<Linter["verifyAndFix"]> {
  return new Linter().verifyAndFix(
    source,
    [{
      files: ["**/*.ts"],
      languageOptions: { parser },
      plugins: { local: { rules: { check: rule } } },
      rules: { "local/check": "error" },
    }],
    { filename },
  );
}

function sources(): { readonly original: string; readonly fixed: string } {
  const example = rule.documentation?.examples.find((entry) => entry.id === "safe-autofix");
  if (example?.files[0] === undefined || example.fixedFiles?.[0] === undefined)
    throw new Error("Missing owned PostgreSQL projection fixture");
  return { original: example.files[0].source, fixed: example.fixedFiles[0].source };
}

it("fixes the actual authored example exactly and converges", () => {
  const { original, fixed } = sources();
  const first = apply(original), second = apply(first.output);
  expect(first.fixed).toBe(true);
  expect(first.output).toBe(fixed);
  expect(first.messages).toEqual([]);
  expect(second.fixed).toBe(false);
  expect(second.output).toBe(fixed);
  expect(second.messages).toEqual([]);
});

it.each(["\n", "\r\n"])("preserves source endings %j", (ending) => {
  const { original, fixed } = sources();
  expect(apply(original.replaceAll("\n", ending)).output).toBe(fixed.replaceAll("\n", ending));
});

it.each([
  ['SELECT * FROM (VALUES (0)) AS "select"("from");', '"select"."from"'],
  ['select * from (values (999999999)) as "A"("MixedCase")', '"A"."MixedCase"'],
  ['SELECT\t*\tFROM\t(VALUES (1,2,3,4,5,6,7,8)) AS "r"("a","b","c","d","e","f","g","h")',
    [..."abcdefgh"].map((name) => `"r"."${name}"`).join(", ")],
  [`SELECT * FROM (VALUES (1)) AS "${"r".repeat(63)}"("${"c".repeat(63)}")`, `"${"r".repeat(63)}"."${"c".repeat(63)}"`],
  ['SELECT * FROM (VALUES (000000001, 2)) AS "r"("A", "a")', '"r"."A", "r"."a"'],
])("expands only the authored star in %s", (query, projection) => {
  const source = sources().original.replace(QUERY, query);
  const result = apply(source);
  expect(result.fixed).toBe(true);
  expect(source.match(/\*/gu)).toHaveLength(1);
  expect(result.output).toBe(source.replaceAll("*", () => projection));
  expect(result.messages).toEqual([]);
  expect(apply(result.output).fixed).toBe(false);
});

it.each([
  'SELECT * FROM (VALUES (1, 2)) AS authored(a, b)',
  'SELECT * FROM (VALUES (1, 2)) AS "r"("a", "a")',
  'SELECT * FROM (VALUES (1, 2)) AS "r"("a")',
  'SELECT * FROM (VALUES (1)) AS "r"("a", "b")',
  'SELECT * FROM (VALUES (1), (2)) AS "r"("a")',
  'SELECT * FROM (VALUES (-1)) AS "r"("a")',
  'SELECT * FROM (VALUES (+1)) AS "r"("a")',
  'SELECT * FROM (VALUES (1.0)) AS "r"("a")',
  'SELECT * FROM (VALUES (1e0)) AS "r"("a")',
  'SELECT * FROM (VALUES (1000000000)) AS "r"("a")',
  'SELECT * FROM (VALUES (NULL)) AS "r"("a")',
  'SELECT * FROM (VALUES (abs(1))) AS "r"("a")',
  'SELECT * FROM (VALUES (1::int)) AS "r"("a")',
  'SELECT * FROM (VALUES (1)) AS "r"("a") WHERE true',
  QUERY + "; SELECT 1",
  QUERY + ' CROSS JOIN (VALUES (3)) AS "s"("c")',
  QUERY.replace("SELECT *", "SELECT /* authored */ *"),
  QUERY.replace("SELECT *", "SELECT -- authored\\n*"),
  `SELECT * FROM (VALUES (1)) AS "${"r".repeat(64)}"("a")`,
  `SELECT * FROM (VALUES (1)) AS "r"("${"c".repeat(64)}")`,
  'SELECT * FROM (VALUES (1,2,3,4,5,6,7,8,9)) AS "r"("a","b","c","d","e","f","g","h","i")',
  QUERY + " ".repeat(2048),
  QUERY.replace('"authored"', '"é"'),
  QUERY.replace('"a"', '"a""b"'),
])("leaves SQL outside the complete closed relation manual: %s", (query) => {
  const source = sources().original.replace(QUERY, query);
  expect(apply(source).fixed).toBe(false);
  expect(apply(source).output).toBe(source);
});

it.each([
  ["from 'pg'", "from 'other'"],
  ["{ Client }", "{ Client as Client }"],
  ["{ Client }", "{ Client, types }"],
  ["import { Client }", "import type { Client }"],
  ["literalRows()", "literalRows(Client)"],
  ["literalRows()", "literalRows<T>()"],
  ["literalRows()", "literalRows(): Promise<unknown>"],
  ["literalRows()", "Client()"],
  ["new Client()", "new Client({ rowMode: 'array' })"],
  ["new Client()", "new Client(configuration)"],
  ["new Client()", "new Client<unknown>()"],
  ["const authoredLiteralClient", "let authoredLiteralClient"],
  ["const authoredLiteralClient =", "const authoredLiteralClient: Client ="],
  ["await authoredLiteralClient.connect();", "await authoredLiteralClient.connect(); observe(authoredLiteralClient);"],
  ["await authoredLiteralClient.connect();", "await authoredLiteralClient.connect(custom);"],
  [`authoredLiteralClient.query('${QUERY}')`, `authoredLiteralClient.query({ text: '${QUERY}' })`],
  [`'${QUERY}'`, `\`${QUERY}\``],
  [`'${QUERY}'`, `String.raw\`${QUERY}\``],
  [`'${QUERY}'`, `sql\`${QUERY}\``],
  ["authoredLiteralClient.query('", "other.query('"],
  ["authoredLiteralClient.query('", "authoredLiteralClient['query']('"],
  ["authoredLiteralClient.query('", "authoredLiteralClient.query?.('"],
  ["SELECT *", "SEL\\u0045CT *"],
  ["SELECT *", "SELECT\\n*"],
  ["await authoredLiteralClient.end();", "await authoredLiteralClient.end(custom);"],
  ["await authoredLiteralClient.end();", "observe(authoredLiteralClient); await authoredLiteralClient.end();"],
  ["import { Client }", "// owned\nimport { Client }"],
  ["export async function", "Client.prototype.query = custom;\nexport async function"],
  ["export async function", "const other = Client;\nexport async function"],
  ["export async function", "export const other = 1;\nexport async function"],
])("refuses configured, unowned or ambiguous source %s -> %s", (before, after) => {
  const source = sources().original.replace(before, after);
  expect(source).not.toBe(sources().original);
  expect(apply(source).fixed).toBe(false);
  expect(apply(source).output).toBe(source);
});

it.each([
  `const query = '${QUERY}'; console.log(query);`,
  `let query = '${QUERY}'; query += ' CROSS JOIN extra';`,
  `function execute(query) { return query; } execute('${QUERY}');`,
  `const query = sql('${QUERY}').format(other);`,
])("keeps actual findings manual for observable text or unknown sinks: %s", (source) => {
  const result = apply(source);
  expect(result.messages).toHaveLength(1);
  expect(result.messages[0]?.messageId).toBe("noSelectStar");
  expect(result.fixed).toBe(false);
  expect(result.output).toBe(source);
});

it.each([
  "tests/rows.ts", "fixtures/rows.ts", "fixture/rows.ts", "scripts/rows.ts",
  "stories/rows.ts", "src/rows.stories.ts", "generated/rows.ts", "external/rows.ts",
])("preserves automatic source ownership exclusion %s", (filename) => {
  const source = sources().original;
  expect(apply(source, filename).fixed).toBe(false);
  expect(apply(source, filename).output).toBe(source);
});
