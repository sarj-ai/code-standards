import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { duplicateTestBodyDocumentation } from "../../src/rules/duplicate-test-body.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({ languageOptions: { parser: tsParser } });
const TEST_FILE = "/repo/src/user.test.ts";

ruleTester.run("duplicate-test-body", rule, {
  valid: [
    {
      name: "allows fewer than three statements",
      filename: TEST_FILE,
      code: `test('one', () => { const result = parse('a'); expect(result).toBe('a'); });
test('two', () => { const result = parse('b'); expect(result).toBe('b'); });`,
    },
    {
      name: "allows structurally different bodies",
      filename: TEST_FILE,
      code: `test('creates', () => { const result = create('a'); expect(result.ok).toBe(true); expect(result.id).toBe('a'); });
test('rejects', () => { const result = create('b'); expect(result.ok).toBe(false); expect(result.error).toBe('bad'); });`,
    },
    {
      name: "does not compare tests in different suites",
      filename: TEST_FILE,
      code: `describe('one', () => { test('a', () => { const x = parse('a'); expect(x.ok).toBe(true); expect(x.value).toBe('a'); }); });
describe('two', () => { test('b', () => { const x = parse('b'); expect(x.ok).toBe(true); expect(x.value).toBe('b'); }); });`,
    },
    {
      name: "allows existing parameterization",
      filename: TEST_FILE,
      code: duplicateTestBodyDocumentation.examples[0].files[0].source,
    },
    {
      name: "does not treat suites or hooks as tests",
      filename: TEST_FILE,
      code: `test.describe('one', () => { seed('a'); run('a'); cleanup('a'); });
test.describe('two', () => { seed('b'); run('b'); cleanup('b'); });
test.beforeEach(() => { seed('a'); run('a'); cleanup('a'); });`,
    },
    {
      name: "does not combine incompatible runner modifiers",
      filename: TEST_FILE,
      code: `test('one', () => { const x = parse('a'); expect(x.ok).toBe(true); expect(x.value).toBe('a'); });
test.skip('two', () => { const x = parse('b'); expect(x.ok).toBe(true); expect(x.value).toBe('b'); });
test.concurrent('three', () => { const x = parse('c'); expect(x.ok).toBe(true); expect(x.value).toBe('c'); });`,
    },
    {
      name: "allows computed each parameterization",
      filename: TEST_FILE,
      code: `test["each"](['a'])('one', (value) => { const x = parse(value); expect(x.ok).toBe(true); expect(x.value).toBe(value); });
test["each"](['b'])('two', (value) => { const x = parse(value); expect(x.ok).toBe(true); expect(x.value).toBe(value); });`,
    },
    {
      name: "preserves runner options and timeouts",
      filename: TEST_FILE,
      code: `test('fast', () => { const x = parse('a'); expect(x.ok).toBe(true); expect(x.value).toBe('a'); }, 100);
test('slow', () => { const x = parse('b'); expect(x.ok).toBe(true); expect(x.value).toBe('b'); }, 10000);`,
    },
    {
      name: "preserves inline snapshots at their callsites",
      filename: TEST_FILE,
      code: `test('one', () => { const x = parse('a'); expect(x.ok).toBe(true); expect(x).toMatchInlineSnapshot('a'); });
test('two', () => { const x = parse('b'); expect(x.ok).toBe(true); expect(x).toMatchInlineSnapshot('b'); });`,
    },
    {
      name: "preserves materially different comments",
      filename: TEST_FILE,
      code: `test('one', () => { const x = parse('a'); /* legacy wire format */ expect(x.ok).toBe(true); expect(x.value).toBe('a'); });
test('two', () => { const x = parse('b'); /* new wire format */ expect(x.ok).toBe(true); expect(x.value).toBe('b'); });`,
    },
    {
      name: "preserves different assertion contracts",
      filename: TEST_FILE,
      code: `test('heading', () => { const view = renderPage(); expect(view.getByRole('heading')).toBeVisible(); expect(view.queryByText('done')).toBeNull(); });
test('completion', () => { const view = renderPage(); expect(view.getByRole('progressbar')).toBeVisible(); expect(view.queryByText('pending')).toBeNull(); });`,
    },
    {
      name: "allows straight-line assertion partitions",
      filename: TEST_FILE,
      code: `test('numeric forms', () => { expect(parse('1')).toBe(1); expect(parse('1.0')).toBe(1); expect(parse('1e0')).toBe(1); });
test('boolean forms', () => { expect(parse('true')).toBe(true); expect(parse('TRUE')).toBe(true); expect(parse('yes')).toBe(true); });`,
    },
    {
      name: "preserves multiline fixture documents",
      filename: TEST_FILE,
      code: "test('one', () => { const x = parse(`first\\nfixture document that must remain distinct because it carries semantics`); expect(x.ok).toBe(true); expect(x.value).toBe('a'); });\ntest('two', () => { const x = parse(`second\\nfixture document that must remain distinct because it carries semantics`); expect(x.ok).toBe(true); expect(x.value).toBe('b'); });",
    },
    {
      name: "does not parameterize compile-time type contracts",
      filename: TEST_FILE,
      code: `it('infers status 400', () => { const req = client.posts.$post; type Actual = InferResponseType<typeof req, 400>; type Expected = { error: 'Bad request' }; type Verify = Expect<Equal<Expected, Actual>>; });
it('infers status 401', () => { const req = client.posts.$post; type Actual = InferResponseType<typeof req, 401>; type Expected = { error: 'Unauthorized' }; type Verify = Expect<Equal<Expected, Actual>>; });`,
    },
    {
      name: "ignores production files",
      filename: "/repo/src/user.ts",
      code: `run('one', () => { const x = parse('a'); save(x); return x; });
run('two', () => { const x = parse('b'); save(x); return x; });`,
    },
    {
      name: "ignores a locally defined function named test",
      filename: TEST_FILE,
      code: `function test(_name: string, callback: () => void) { callback(); }
test('one', () => { const x = parse('a'); save(x); cleanup(x); });
test('two', () => { const x = parse('b'); save(x); cleanup(x); });`,
    },
    {
      name: "ignores a locally defined function named it",
      filename: TEST_FILE,
      code: `const it = (_name: string, callback: () => void) => callback();
it('one', () => { const x = parse('a'); save(x); cleanup(x); });
it('two', () => { const x = parse('b'); save(x); cleanup(x); });`,
    },
    {
      name: "ignores test imported from a non-runner module",
      filename: TEST_FILE,
      code: `import { test } from './application-test-helper';
test('one', () => { const x = parse('a'); save(x); cleanup(x); });
test('two', () => { const x = parse('b'); save(x); cleanup(x); });`,
    },
  ],
  invalid: [
    {
      name: "reports the later sibling whose body differs only by case literals",
      filename: TEST_FILE,
      code: duplicateTestBodyDocumentation.examples[1].files[0].source,
      errors: [{ messageId: "duplicateTestBody", line: 2 }],
    },
    {
      name: "reports every additional copy after the first",
      filename: TEST_FILE,
      code: `it('one', async () => { const x = await load(1); expect(x.ok).toBe(true); expect(x.id).toBeDefined(); });
it('two', async () => { const x = await load(2); expect(x.ok).toBe(true); expect(x.id).toBeDefined(); });
it('three', async () => { const x = await load(3); expect(x.ok).toBe(true); expect(x.id).toBeDefined(); });`,
      errors: [
        { messageId: "duplicateTestBody", line: 2 },
        { messageId: "duplicateTestBody", line: 3 },
      ],
    },
    {
      name: "reports exact copies as well as literal variants",
      filename: "/repo/tests/parse.ts",
      code: `test('one', () => { const x = parse(input); expect(x.ok).toBe(true); expect(x.value).toBe(input); });
test('two', () => { const x = parse(input); expect(x.ok).toBe(true); expect(x.value).toBe(input); });`,
      errors: [{ messageId: "duplicateTestBody", line: 2 }],
    },
    {
      name: "reports non-adjacent duplicate siblings",
      filename: TEST_FILE,
      code: `test('first parse', () => { const x = parse('a'); expect(x.ok).toBe(true); expect(x.value).toBeDefined(); });
test('unrelated behavior', () => { const record = createRecord(); save(record); expect(record.id).toBeDefined(); });
test('second parse', () => { const x = parse('b'); expect(x.ok).toBe(true); expect(x.value).toBeDefined(); });`,
      errors: [{ messageId: "duplicateTestBody", line: 3 }],
    },
  ],
});
