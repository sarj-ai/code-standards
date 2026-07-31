import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-tautological-expect.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

const TEST_FILE = "/repo/src/tests/dummy.test.ts";

ruleTester.run("no-tautological-expect", rule, {
  valid: [
    // --- The critical FP guard, measured at ~95% of naive-rule hits: comparing a
    // real value with itself is a reflexivity / determinism / memoization test,
    // and for a type with custom equality it can genuinely fail. ---
    {
      filename: TEST_FILE,
      code: "it('hashes deterministically', () => { expect(hash([o])).toEqual(hash([o])); });",
    },
    {
      filename: TEST_FILE,
      code: "it('is reflexive', () => { expect(a).toEqual(a); });",
    },
    {
      filename: TEST_FILE,
      code: "it('memoizes', () => { expect(memo(x)).toBe(memo(x)); });",
    },
    {
      filename: TEST_FILE,
      code: "it('is stable', () => { expect(config.value).toBe(config.value); });",
    },
    // --- One literal side only: this is an ordinary assertion. ---
    {
      filename: TEST_FILE,
      code: "it('returns two', () => { expect(add(1, 1)).toBe(2); });",
    },
    {
      filename: TEST_FILE,
      code: "it('is defined', () => { expect(result).toBeDefined(); });",
    },
    // --- Two DIFFERENT literals: always fails, which is loud on the first run. ---
    {
      filename: TEST_FILE,
      code: "it('is one', () => { expect(1).toBe(2); });",
    },
    {
      filename: TEST_FILE,
      code: "it('same value, different spelling', () => { expect(1).toBe(1.0); });",
    },
    // --- A modified chain is outside the shape the rule can reason about. ---
    {
      filename: TEST_FILE,
      code: "it('negates', () => { expect(true).not.toBe(false); });",
    },
    {
      filename: TEST_FILE,
      code: "it('resolves', async () => { await expect(promise).resolves.toBe(1); });",
    },
    // --- Spread and interpolation depend on runtime values. ---
    {
      filename: TEST_FILE,
      code: "it('spreads', () => { expect([...xs]).toEqual([...xs]); });",
    },
    {
      filename: TEST_FILE,
      code: "it('interpolates', () => { expect(`${id}`).toEqual(`${id}`); });",
    },
    {
      filename: TEST_FILE,
      code: "it('spreads an object', () => { expect({ ...base }).toBeTruthy(); });",
    },
    // --- A matcher that takes arguments is not the zero-arg shape. ---
    {
      filename: TEST_FILE,
      code: "it('closes', () => { expect(0.1).toBeCloseTo(sum); });",
    },
    // --- Not `expect` at all. ---
    {
      filename: TEST_FILE,
      code: "it('parses', () => { parser(true).toBe(true); });",
    },
    // --- Production code is out of scope; `expect` there is somebody else's API. ---
    {
      filename: "/repo/src/parser.ts",
      code: "export const check = () => expect(true).toBe(true);",
    },
  ],
  invalid: [
    // --- The three known real hits, verbatim. ---
    {
      filename: "/repo/apps/worker/test/handler.test.ts",
      code: [
        "it('disambiguates a customer record', () => {",
        "  expect(true).toBe(true); // placeholder",
        "});",
      ].join("\n"),
      errors: [{ messageId: "tautologicalComparison" }],
    },
    {
      filename: TEST_FILE,
      code: "it('works', () => { expect(true).toBe(true); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
    {
      filename: TEST_FILE,
      code: "it('works', () => { expect(1).toEqual(1); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
    // --- Every equality matcher. ---
    {
      filename: TEST_FILE,
      code: "it('works', () => { expect('a').toStrictEqual('a'); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
    // --- Composite literals, textually identical. ---
    {
      filename: TEST_FILE,
      code: "it('works', () => { expect([1, 2]).toEqual([1, 2]); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
    {
      filename: TEST_FILE,
      code: "it('works', () => { expect({ a: 1 }).toEqual({ a: 1 }); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
    {
      filename: TEST_FILE,
      code: "it('works', () => { expect(-1).toBe(-1); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
    {
      filename: TEST_FILE,
      code: "it('works', () => { expect(`fixed`).toEqual(`fixed`); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
    // --- Zero-argument matchers on a literal receiver. ---
    {
      filename: TEST_FILE,
      code: "it('works', () => { expect(true).toBeDefined(); });",
      errors: [{ messageId: "tautologicalMatcher" }],
    },
    {
      filename: TEST_FILE,
      code: "it('works', () => { expect('x').toBeTruthy(); });",
      errors: [{ messageId: "tautologicalMatcher" }],
    },
    {
      filename: TEST_FILE,
      code: "it('works', () => { expect(null).toBeNull(); });",
      errors: [{ messageId: "tautologicalMatcher" }],
    },
    {
      filename: TEST_FILE,
      code: "it('works', () => { expect([]).toBeFalsy(); });",
      errors: [{ messageId: "tautologicalMatcher" }],
    },
    // --- Several in one body are reported one apiece. ---
    {
      filename: TEST_FILE,
      code: [
        "it('placeholder suite', () => {",
        "  expect(true).toBe(true);",
        "  expect(1).toEqual(1);",
        "});",
      ].join("\n"),
      errors: [{ messageId: "tautologicalComparison" }, { messageId: "tautologicalComparison" }],
    },
    // --- A `tests/` directory counts as a test file even without the suffix. ---
    {
      filename: "/repo/src/tests/dummy.ts",
      code: "it('works', () => { expect(true).toBe(true); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
  ],
});
