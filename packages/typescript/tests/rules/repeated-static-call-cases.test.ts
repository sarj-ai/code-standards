// vitest: shared-module-graph
import duplicateTestBody from "../../src/rules/duplicate-test-body.js";
import rule from "../../src/rules/repeated-static-call-cases.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

const TEST_FILE = "/repo/src/parser.test.ts";

RULE_TESTER.run("repeated-static-call-cases", rule, {
  valid: [
    { name: "preserves an ordered stateful closure scenario", filename: TEST_FILE, code: "test('sum', () => { let n = 0; const add = x => n += x; expect(add(1)).toBe(1); expect(add(2)).toBe(3); expect(add(3)).toBe(6); });" },
    { name: "preserves a test-local function declaration", filename: TEST_FILE, code: "test('sum', () => { let n = 0; function add(x) { return n += x; } expect(add(1)).toBe(1); expect(add(2)).toBe(3); expect(add(3)).toBe(6); });" },
    { name: "preserves a callback parameter fixture", filename: TEST_FILE, code: "test('sum', (add) => { expect(add(1)).toBe(1); expect(add(2)).toBe(3); expect(add(3)).toBe(6); });" },
    { name: "public no-match example", filename: "src/parser.test.ts", code: "test.each([['a', true], ['b', false], ['c', true]])('parses %s', (input, expected) => { expect(parse(input)).toBe(expected); });" },
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
    { name: "repeated-dynamic-member", filename: "src/parser.test.ts", code: "test('parses', () => { expect(parse('a'))[auditDynamicMember](true); expect(parse('b'))[auditDynamicMember](false); expect(parse('c'))[auditDynamicMember](true); });" },
    { name: "ignores generated headers", filename: TEST_FILE, code: "// @generated\ntest('x', () => { expect(parse('a')).toBe(1); expect(parse('b')).toBe(2); expect(parse('c')).toBe(3); });" },
  ],
  invalid: [
    { name: "public match example", filename: "src/parser.test.ts", code: "test('parses', () => { expect(parse('a')).toBe(true); expect(parse('b')).toBe(false); expect(parse('c')).toBe(true); });", errors: [{ messageId: "repeatedStaticCallCases", data: { count: "3" } }] },
    { name: "supports imported aliases and modifiers", filename: TEST_FILE, code: "import { test as check, expect as verify } from 'vitest'; check.only('x', () => { verify(parse('a')).not.toBe(1); verify(parse('b')).not.toBe(2); verify(parse('c')).not.toBe(3); });", errors: [{ messageId: "repeatedStaticCallCases", data: { count: "3" } }] },
    { name: "reports once for a longer run", filename: TEST_FILE, code: "it('x', () => { expect(parse('a', 1)).toEqual(true); expect(parse('b', 2)).toEqual(false); expect(parse('c', 3)).toEqual(true); expect(parse('d', 4)).toEqual(false); });", errors: [{ messageId: "repeatedStaticCallCases", data: { count: "4" } }] },
    { name: "repeated-static-member", filename: "src/parser.test.ts", code: "test('parses', () => { expect(parse('a'))[\"toBe\"](true); expect(parse('b'))[\"toBe\"](false); expect(parse('c'))[\"toBe\"](true); });", errors: [{ messageId: "repeatedStaticCallCases", data: { count: "3" } }] },
    { name: "allows static arrays and objects", filename: TEST_FILE, code: "test.concurrent('x', () => { expect(parse({ x: 1 })).toEqual(['a']); expect(parse({ x: 2 })).toEqual(['b']); expect(parse({ x: 3 })).toEqual(['c']); });", errors: [{ messageId: "repeatedStaticCallCases", data: { count: "3" } }] },
  ],
});

const DUPLICATED_CALLBACKS = `test('first', () => { const family = 'numbers'; expect(parse('1')).toBe(1); expect(parse('1.0')).toBe(1); expect(parse('1e0')).toBe(1); });
test('second', () => { const family = 'numbers'; expect(parse('1')).toBe(1); expect(parse('1.0')).toBe(1); expect(parse('1e0')).toBe(1); });`;

RULE_TESTER.run("repeated-static-call-cases defers to duplicate-test-body", rule, {
  valid: [{ name: "defers a duplicated callback to duplicate-test-body (the original's two-rule Linter check, split per rule)", filename: "src/parser.test.ts", code: DUPLICATED_CALLBACKS }],
  invalid: [],
});

RULE_TESTER.run("duplicate-test-body reports the duplicated callback", duplicateTestBody, {
  valid: [],
  invalid: [{ name: "defers a duplicated callback to duplicate-test-body (the original's two-rule Linter check, split per rule)", filename: "src/parser.test.ts", code: DUPLICATED_CALLBACKS, errors: [{ messageId: "duplicateTestBody" }] }],
});
