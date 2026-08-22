import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import duplicateTestBody from "../../src/rules/duplicate-test-body.js";
import rule, { REPEATED_STATIC_CALL_CASES_DOCUMENTATION } from "../../src/rules/repeated-static-call-cases.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });
const TEST_FILE = "/repo/src/parser.test.ts";

RULE_TESTER.run("repeated-static-call-cases", rule, {
  valid: [
    { name: "public no-match example", filename: REPEATED_STATIC_CALL_CASES_DOCUMENTATION.examples[0].focusPath, code: REPEATED_STATIC_CALL_CASES_DOCUMENTATION.examples[0].files[0].source },
    { name: "requires three cases", filename: TEST_FILE, code: "test('x', () => { expect(parse('a')).toBe(1); expect(parse('b')).toBe(2); });" },
    { name: "requires varying cases", filename: TEST_FILE, code: "test('x', () => { expect(parse('a')).toBe(1); expect(parse('a')).toBe(1); expect(parse('a')).toBe(1); });" },
    { name: "excludes zero argument state sequences", filename: TEST_FILE, code: "test('x', () => { expect(next()).toBe(1); expect(next()).toBe(2); expect(next()).toBe(3); });" },
    { name: "excludes dynamic arguments", filename: TEST_FILE, code: "test('x', () => { expect(parse(first)).toBe(1); expect(parse(second)).toBe(2); expect(parse(third)).toBe(3); });" },
    { name: "excludes member queries and locators", filename: TEST_FILE, code: "test('x', () => { expect(page.locator('a')).toBeVisible(); expect(page.locator('b')).toBeVisible(); expect(page.locator('c')).toBeVisible(); });" },
    { name: "excludes mock factory member calls", filename: TEST_FILE, code: "test('x', () => { expect(vi.fn('a')).toBe('a'); expect(vi.fn('b')).toBe('b'); expect(vi.fn('c')).toBe('c'); });" },
    { name: "excludes snapshots", filename: TEST_FILE, code: "test('x', () => { expect(parse('a')).toMatchSnapshot('a'); expect(parse('b')).toMatchSnapshot('b'); expect(parse('c')).toMatchSnapshot('c'); });" },
    { name: "setup interrupts a run", filename: TEST_FILE, code: "test('x', () => { expect(parse('a')).toBe(1); setup(); expect(parse('b')).toBe(2); expect(parse('c')).toBe(3); });" },
    { name: "a comment makes intent non-mechanical", filename: TEST_FILE, code: "test('x', () => { expect(parse('a')).toBe(1); // boundary\n expect(parse('b')).toBe(2); expect(parse('c')).toBe(3); });" },
    { name: "different matchers are separate runs", filename: TEST_FILE, code: "test('x', () => { expect(parse('a')).toBe(1); expect(parse('b')).toEqual(2); expect(parse('c')).toBe(3); });" },
    { name: "different literal structures are separate runs", filename: TEST_FILE, code: "test('x', () => { expect(parse('a')).toBe(1); expect(parse({ value: 'b' })).toBe(2); expect(parse(['c'])).toBe(3); });" },
    { name: "ignores nested helper ownership", filename: TEST_FILE, code: "test('x', () => { const check = () => { expect(parse('a')).toBe(1); expect(parse('b')).toBe(2); expect(parse('c')).toBe(3); }; check(); });" },
    { name: "ignores local test and expect bindings", filename: TEST_FILE, code: "const test = (_n, f) => f(); const expect = (x) => x; test('x', () => { expect(parse('a')).toBe(1); expect(parse('b')).toBe(2); expect(parse('c')).toBe(3); });" },
    { name: "ignores imports from unsupported modules", filename: TEST_FILE, code: "import { test, expect } from './helpers'; test('x', () => { expect(parse('a')).toBe(1); expect(parse('b')).toBe(2); expect(parse('c')).toBe(3); });" },
    { name: "ignores production files", filename: "/repo/src/parser.ts", code: "test('x', () => { expect(parse('a')).toBe(1); expect(parse('b')).toBe(2); expect(parse('c')).toBe(3); });" },
    { name: "ignores generated paths", filename: "/repo/src/generated/parser.test.ts", code: "test('x', () => { expect(parse('a')).toBe(1); expect(parse('b')).toBe(2); expect(parse('c')).toBe(3); });" },
    { name: "ignores generated headers", filename: TEST_FILE, code: "// @generated\ntest('x', () => { expect(parse('a')).toBe(1); expect(parse('b')).toBe(2); expect(parse('c')).toBe(3); });" },
  ],
  invalid: [
    { name: "public match example", filename: REPEATED_STATIC_CALL_CASES_DOCUMENTATION.examples[1].focusPath, code: REPEATED_STATIC_CALL_CASES_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "repeatedStaticCallCases", data: { count: "3" } }] },
    { name: "supports imported aliases and modifiers", filename: TEST_FILE, code: "import { test as check, expect as verify } from 'vitest'; check.only('x', () => { verify(parse('a')).not.toBe(1); verify(parse('b')).not.toBe(2); verify(parse('c')).not.toBe(3); });", errors: [{ messageId: "repeatedStaticCallCases", data: { count: "3" } }] },
    { name: "reports once for a longer run", filename: TEST_FILE, code: "it('x', () => { expect(parse('a', 1)).toEqual(true); expect(parse('b', 2)).toEqual(false); expect(parse('c', 3)).toEqual(true); expect(parse('d', 4)).toEqual(false); });", errors: [{ messageId: "repeatedStaticCallCases", data: { count: "4" } }] },
    { name: "allows static arrays and objects", filename: TEST_FILE, code: "test.concurrent('x', () => { expect(parse({ x: 1 })).toEqual(['a']); expect(parse({ x: 2 })).toEqual(['b']); expect(parse({ x: 3 })).toEqual(['c']); });", errors: [{ messageId: "repeatedStaticCallCases", data: { count: "3" } }] },
  ],
});

it("defers a duplicated callback to duplicate-test-body", () => {
  const code = `test('first', () => { const family = 'numbers'; expect(parse('1')).toBe(1); expect(parse('1.0')).toBe(1); expect(parse('1e0')).toBe(1); });
test('second', () => { const family = 'numbers'; expect(parse('1')).toBe(1); expect(parse('1.0')).toBe(1); expect(parse('1e0')).toBe(1); });`;
  const linter = new Linter({ configType: "flat" });
  const messages = linter.verify(code, [
    {
      files: ["**/*.ts"],
      languageOptions: { parser: tsParser },
      plugins: {
        local: {
          rules: {
            "duplicate-test-body": duplicateTestBody,
            "repeated-static-call-cases": rule,
          },
        },
      },
      rules: {
        "local/duplicate-test-body": "error",
        "local/repeated-static-call-cases": "warn",
      },
    },
  ], "src/parser.test.ts");
  expect(messages.map((message) => message.ruleId)).toEqual(["local/duplicate-test-body"]);
});
