import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-conditional-in-test.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

const TEST_FILE = "/repo/src/component.test.ts";

ruleTester.run("no-conditional-in-test", rule, {
  valid: [
    {
      filename: TEST_FILE,
      code: "it('works without conditionals', () => { expect(1).toBe(1); });",
    },
    {
      filename: TEST_FILE,
      code: "test('works without conditionals', () => { const a = 1; expect(a).toBe(1); });",
    },
    {
      filename: TEST_FILE,
      code: "it('allows conditionals in helper functions', () => { const helper = (b) => { if (b) return 1; return 2; }; expect(helper(true)).toBe(1); });",
    },
    {
      filename: "/repo/src/component.ts",
      code: "export function comp(a) { if (a) { return true; } return false; }",
    },
    {
      filename: TEST_FILE,
      code: "describe('suite', () => { if (process.env.CI) { it('runs', () => { expect(true).toBe(true); }); } });",
    },
  ],
  invalid: [
    {
      filename: TEST_FILE,
      code: "it('fails with if', () => { if (true) { expect(1).toBe(1); } });",
      errors: [{ messageId: "noConditionalInTest" }],
    },
    {
      filename: TEST_FILE,
      code: "test('fails with switch', () => { switch (a) { case 1: expect(1).toBe(1); } });",
      errors: [{ messageId: "noConditionalInTest" }],
    },
    {
      filename: TEST_FILE,
      code: "it('fails with ternary', () => { const a = b ? 1 : 2; expect(a).toBe(1); });",
      errors: [{ messageId: "noConditionalInTest" }],
    },
    {
      filename: TEST_FILE,
      code: "it('fails with logical expression', () => { a && expect(a).toBe(1); });",
      errors: [{ messageId: "noConditionalInTest" }],
    },
    {
      filename: TEST_FILE,
      code: "it.only('fails on variants', () => { if (a) { expect(a).toBe(1); } });",
      errors: [{ messageId: "noConditionalInTest" }],
    },
  ],
});
