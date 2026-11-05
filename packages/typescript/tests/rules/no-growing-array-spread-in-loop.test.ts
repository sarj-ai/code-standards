import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  NO_GROWING_ARRAY_SPREAD_IN_LOOP_DOCUMENTATION,
} from "../../src/rules/no-growing-array-spread-in-loop.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const TESTER = new RuleTester({
  languageOptions: {
    parser,
    parserOptions: {
      projectService: { allowDefaultProject: ["*.ts*"] },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});

TESTER.run("no-growing-array-spread-in-loop", rule, {
  valid: [
    NO_GROWING_ARRAY_SPREAD_IN_LOOP_DOCUMENTATION.examples[1].files[0].source,
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
      code: NO_GROWING_ARRAY_SPREAD_IN_LOOP_DOCUMENTATION.examples[0].files[0]
        .source,
      output: null,
      errors: [{ messageId: "copy" }],
    },
    {
      code: "function collect(input: string[]) { let rows: string[] = []; for (const row of input) rows = [...rows, row]; return rows; }",
      output: null,
      errors: [{ messageId: "copy" }],
    },
  ],
});

const SYNTAX_TESTER = new RuleTester({ languageOptions: { parser } });
SYNTAX_TESTER.run("no-growing-array-spread-in-loop without types", rule, {
  valid: [
    NO_GROWING_ARRAY_SPREAD_IN_LOOP_DOCUMENTATION.examples[0].files[0].source,
  ],
  invalid: [],
});
TESTER.run("no-growing-array-spread-in-loop audited boundaries", rule, {
  valid: [
    {
      name: "preserves fixed literal loop costs",
      code: "function collect() { let rows: string[] = []; for (const row of ['a', 'b', 'c']) { rows = [...rows, row]; } return rows; }",
    },
  ],
  invalid: [],
});
TESTER.run("no-growing-array-spread-in-loop bounded sources", rule, {
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
});
