import { join } from "node:path";

import { RuleTester } from "oxlint/plugins-dev";
import { describe, it } from "vitest";

import rule from "../../src/rules/no-growing-array-spread-in-loop.js";

RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const COPY_PREFIX_EXAMPLE =
  "export function collect(input: string[]) { let rows: string[] = []; for (const row of input) { rows = [...rows, row]; } return rows; }";
const APPEND_ROWS_EXAMPLE =
  "export function collect(input: string[]) { const rows: string[] = []; for (const row of input) { rows.push(row); } return rows; }";

const TESTER = new RuleTester({
  eslintCompat: true,
  languageOptions: { parserOptions: { lang: "ts" } },
});

TESTER.run("no-growing-array-spread-in-loop without types", rule, {
  valid: [{ code: COPY_PREFIX_EXAMPLE, settings: { sarj: { typeAware: false } } }],
  invalid: [],
});

const TYPED_TESTER = new RuleTester({
  eslintCompat: true,
  cwd: join(import.meta.dirname, "..", "fixtures"),
  languageOptions: { parserOptions: { lang: "ts" } },
});

const TYPE_AWARE = { sarj: { typeAware: true } };
function typed(cases: RuleTester.TestCases): RuleTester.TestCases {
  return {
    // eslint-disable-next-line @sarj/no-runtime-typeof -- Oxlint's RuleTester takes a valid case as a bare code string or an untagged case object.
    valid: cases.valid.map((test) => ({ ...(typeof test === "string" ? { code: test } : test), settings: TYPE_AWARE })),
    invalid: cases.invalid.map((test) => ({ ...test, settings: TYPE_AWARE })),
  };
}

TYPED_TESTER.run("no-growing-array-spread-in-loop", rule, typed({
  valid: [
    APPEND_ROWS_EXAMPLE,
    "function collect(input: string[]) { for (const row of input) { let rows: string[] = []; rows = [...rows, row]; } }",
    "function collect(input: string[]) { let rows: string[] = []; for (const row of input) { rows = []; rows = [...rows, row]; } return rows; }",
    "function collect(input: string[]) { let rows: string[] = []; const snapshots: string[][] = []; for (const row of input) { snapshots.push(rows); rows = [...rows, row]; } return rows; }",
    "function collect(input: string[]) { let rows: string[] = []; observe(rows); for (const row of input) { rows = [...rows, row]; } return rows; }",
    "function collect(input: string[]) { let rows: string[] = []; for (const row of input) { rows = rows.concat(row); } return rows; }",
    "function collect(input: string[]) { let rows: string[] = []; for (const row of input) { rows = [...rows, row]; break; } return rows; }",
    "function collect() { let rows: string[] = []; for (const row of ['only']) { rows = [...rows, row]; } return rows; }",
    "function collect(input: string[]) { let rows: string[] = []; for (const row of input) { rows = [...rows, ...input]; } return rows; }",
    "function collect(input: string[]) { let rows: string[] = []; const read = () => rows; for (const row of input) { rows = [...rows, row]; } return read; }",
    "export let rows: string[] = []; declare const input: string[]; for (const row of input) { rows = [...rows, row]; }",
    "let rows: string[] = []; declare const input: string[]; for (const row of input) { rows = [...rows, row]; } export { rows };",
    {
      filename: "generated.ts",
      code: "// @generated\nfunction collect(input: string[]) { let rows: string[] = []; for (const row of input) { rows = [...rows, row]; } return rows; }",
    },
  ],
  invalid: [
    {
      code: COPY_PREFIX_EXAMPLE,
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      code: "function collect(input: string[]) { let rows: string[] = []; for (const row of input) rows = [...rows, row]; return rows; }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
  ],
}));

TYPED_TESTER.run("no-growing-array-spread-in-loop audited boundaries", rule, typed({
  valid: [
    {
      name: "preserves fixed literal loop costs",
      code: "function collect() { let rows: string[] = []; for (const row of ['a', 'b', 'c']) { rows = [...rows, row]; } return rows; }",
    },
  ],
  invalid: [],
}));

TYPED_TESTER.run("no-growing-array-spread-in-loop bounded sources", rule, typed({
  valid: [
    "function collect() { const input = ['a', 'b']; let rows: string[] = []; for (const row of input) { rows = [...rows, row]; } return rows; }",
    "function collect() { const fixed = ['a', 'b']; const input = fixed; let rows: string[] = []; for (const row of input) { rows = [...rows, row]; } return rows; }",
    "function collect(input: string[]) { let rows: string[] = []; for (const row of input.slice(0, 3)) { rows = [...rows, row]; } return rows; }",
    "function collect() { let rows: string[] = []; for (const row of Array.of('a', 'b')) { rows = [...rows, row]; } return rows; }",
    "function collect() { const data = { input: ['a', 'b'] }; let rows: string[] = []; for (const row of data.input) { rows = [...rows, row]; } return rows; }",
  ],
  invalid: [
    {
      name: "retains parameter alias coverage",
      code: "function collect(input: string[]) { const source = input; let rows: string[] = []; for (const row of source) { rows = [...rows, row]; } return rows; }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
  ],
}));
