import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/test-loops-over-literal-cases.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({ languageOptions: { parser: tsParser } });
const TEST_FILE = "/repo/src/parser.test.ts";

ruleTester.run("test-loops-over-literal-cases", rule, {
  valid: [
    {
      name: "allows a single inline case",
      filename: TEST_FILE,
      code: "test('parses', () => { for (const value of ['a']) expect(parse(value)).toBe(value); });",
    },
    {
      name: "allows a computed case source",
      filename: TEST_FILE,
      code: "test('parses', () => { for (const value of cases) expect(parse(value)).toBe(value); });",
    },
    {
      name: "allows a spread case source",
      filename: TEST_FILE,
      code: "test('parses', () => { for (const value of ['a', ...extra]) expect(parse(value)).toBe(value); });",
    },
    {
      name: "allows setup loops without assertions",
      filename: TEST_FILE,
      code: "test('seeds', () => { for (const value of ['a', 'b']) database.seed(value); expect(database.size).toBe(2); });",
    },
    {
      name: "allows assertions inside a nested helper",
      filename: TEST_FILE,
      code: "test('builds cases', () => { for (const value of ['a', 'b']) { callbacks.push(() => expect(parse(value)).toBe(value)); } });",
    },
    {
      name: "allows a runner-aware subtest per iteration",
      filename: TEST_FILE,
      code: "test('parses', async (t) => { for (const value of ['a', 'b']) { await t.test(value, () => { expect(parse(value)).toBe(value); }); } });",
    },
    {
      name: "allows ordered stateful scenarios",
      filename: TEST_FILE,
      code: "test('migrates in order', () => { let state = initial; for (const version of [1, 2, 3]) { state = migrate(state, version); expect(state.version).toBe(version); } });",
    },
    {
      name: "allows loops with early control flow",
      filename: TEST_FILE,
      code: "test('finds first', () => { for (const value of ['a', 'b']) { if (matches(value)) break; expect(parse(value)).toBe(value); } });",
    },
    {
      name: "does not treat suite or setup callbacks as tests",
      filename: TEST_FILE,
      code: "test.describe('suite', () => { for (const value of ['a', 'b']) expect(parse(value)).toBe(value); }); test.beforeEach(() => { for (const value of ['a', 'b']) expect(parse(value)).toBe(value); });",
    },
    {
      name: "ignores loops in helper functions",
      filename: TEST_FILE,
      code: "const check = () => { for (const value of ['a', 'b']) expect(parse(value)).toBe(value); }; test('parses', check);",
    },
    {
      name: "ignores production files",
      filename: "/repo/src/parser.ts",
      code: "export function check() { for (const value of ['a', 'b']) expect(parse(value)).toBe(value); }",
    },
    {
      name: "ignores a locally defined function named test",
      filename: TEST_FILE,
      code: "function test(_name: string, callback: () => void) { callback(); } test('local', () => { for (const value of ['a', 'b']) expect(parse(value)).toBe(value); });",
    },
    {
      name: "ignores a locally defined assertion named expect",
      filename: TEST_FILE,
      code: "const expect = (value: unknown) => consume(value); test('runner', () => { for (const value of ['a', 'b']) expect(parse(value)); });",
    },
  ],
  invalid: [
    {
      name: "reports scalar literal cases",
      filename: TEST_FILE,
      code: "test('parses', () => { for (const value of ['a', 'b']) { expect(parse(value)).toBe(value); } });",
      errors: [{ messageId: "literalCaseLoop", data: { count: "2" } }],
    },
    {
      name: "reports tuple-shaped cases",
      filename: TEST_FILE,
      code: "it('adds', () => { for (const [left, right, total] of [[1, 2, 3], [2, 3, 5]]) { expect(add(left, right)).toBe(total); } });",
      errors: [{ messageId: "literalCaseLoop", data: { count: "2" } }],
    },
    {
      name: "reports object-shaped cases and chained assertions",
      filename: "/repo/tests/parser.ts",
      code: "test.only('parses', () => { for (const sample of [{ input: 'a', ok: true }, { input: '!', ok: false }]) expect(parse(sample.input)).toMatchObject({ ok: sample.ok }); });",
      errors: [{ messageId: "literalCaseLoop", data: { count: "2" } }],
    },
    {
      name: "reports a loop nested in test control flow",
      filename: TEST_FILE,
      code: "test('parses', () => { if (enabled) { for (const value of [1, 2, 3]) assert.equal(parse(value), value); } });",
      errors: [{ messageId: "literalCaseLoop", data: { count: "3" } }],
    },
    {
      name: "ordinary application test calls do not masquerade as subtests",
      filename: TEST_FILE,
      code: "test('parses', () => { for (const value of ['a', 'b']) { expect(subject.test(value)).toBe(true); } });",
      errors: [{ messageId: "literalCaseLoop", data: { count: "2" } }],
    },
    {
      name: "application test methods with callbacks do not masquerade as subtests",
      filename: TEST_FILE,
      code: "test('parses', () => { for (const value of ['a', 'b']) { expect(subject.test(value, () => true)).toBe(true); } });",
      errors: [{ messageId: "literalCaseLoop", data: { count: "2" } }],
    },
    {
      name: "reports const-asserted literal cases",
      filename: TEST_FILE,
      code: "test('parses', () => { for (const value of ['a', 'b'] as const) expect(parse(value)).toBe(value); });",
      errors: [{ messageId: "literalCaseLoop", data: { count: "2" } }],
    },
  ],
});
