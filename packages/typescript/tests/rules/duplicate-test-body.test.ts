// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { DUPLICATE_TEST_BODY_DOCUMENTATION } from "../../src/rules/duplicate-test-body.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });
const TEST_FILE = "/repo/src/user.test.ts";

RULE_TESTER.run("duplicate-test-body", rule, {
  valid: [
    { name: "native named node:assert equal: distinct contracts", filename: TEST_FILE, code: "import {test} from 'node:test';import {equal as verify} from 'node:assert';test('a',()=>{const result=read('a');verify(result.code, \"a\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"b\"); verify(result.size, 2);});" },
    { name: "native named node:assert strictEqual: distinct contracts", filename: TEST_FILE, code: "import {test} from 'node:test';import {strictEqual as verify} from 'node:assert';test('a',()=>{const result=read('a');verify(result.code, \"a\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"b\"); verify(result.size, 2);});" },
    { name: "native named node:assert deepEqual: distinct contracts", filename: TEST_FILE, code: "import {test} from 'node:test';import {deepEqual as verify} from 'node:assert';test('a',()=>{const result=read('a');verify(result.code, \"a\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"b\"); verify(result.size, 2);});" },
    { name: "native named node:assert deepStrictEqual: distinct contracts", filename: TEST_FILE, code: "import {test} from 'node:test';import {deepStrictEqual as verify} from 'node:assert';test('a',()=>{const result=read('a');verify(result.code, \"a\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"b\"); verify(result.size, 2);});" },
    { name: "native named node:assert ok: distinct contracts", filename: TEST_FILE, code: "import {test} from 'node:test';import {ok as verify} from 'node:assert';test('a',()=>{const result=read('a');verify(result.code === \"a\"); verify(result.size === 1);});test('b',()=>{const result=read('b');verify(result.code === \"b\"); verify(result.size === 2);});" },
    { name: "native named node:assert/strict equal: distinct contracts", filename: TEST_FILE, code: "import {test} from 'node:test';import {equal as verify} from 'node:assert/strict';test('a',()=>{const result=read('a');verify(result.code, \"a\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"b\"); verify(result.size, 2);});" },
    { name: "native named node:assert/strict strictEqual: distinct contracts", filename: TEST_FILE, code: "import {test} from 'node:test';import {strictEqual as verify} from 'node:assert/strict';test('a',()=>{const result=read('a');verify(result.code, \"a\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"b\"); verify(result.size, 2);});" },
    { name: "native named node:assert/strict deepEqual: distinct contracts", filename: TEST_FILE, code: "import {test} from 'node:test';import {deepEqual as verify} from 'node:assert/strict';test('a',()=>{const result=read('a');verify(result.code, \"a\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"b\"); verify(result.size, 2);});" },
    { name: "native named node:assert/strict deepStrictEqual: distinct contracts", filename: TEST_FILE, code: "import {test} from 'node:test';import {deepStrictEqual as verify} from 'node:assert/strict';test('a',()=>{const result=read('a');verify(result.code, \"a\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"b\"); verify(result.size, 2);});" },
    { name: "native named node:assert/strict ok: distinct contracts", filename: TEST_FILE, code: "import {test} from 'node:test';import {ok as verify} from 'node:assert/strict';test('a',()=>{const result=read('a');verify(result.code === \"a\"); verify(result.size === 1);});test('b',()=>{const result=read('b');verify(result.code === \"b\"); verify(result.size === 2);});" },
    { name: "assertion provenance: named-expect-different-literal-contract", filename: TEST_FILE, code: "import {test,expect as verify} from 'vitest';test('a',()=>{const value=parse('a');verify(value).toBe('a');cleanup();});test('b',()=>{const value=parse('b');verify(value).toBe('b');cleanup();});" },
    { name: "assertion provenance: named-expect-assertions-only", filename: TEST_FILE, code: "import {test,expect as verify} from 'vitest';test('a',()=>{verify(value).toBe('a');verify(value).toBe('a');verify(value).toBe('a');});test('b',()=>{verify(value).toBe('b');verify(value).toBe('b');verify(value).toBe('b');});" },
    { name: "assertion provenance: named-vitest-assert-different-literal-contract", filename: TEST_FILE, code: "import {test,assert as verify} from 'vitest';test('a',()=>{const value=parse('a');verify.equal(value,'a');cleanup();});test('b',()=>{const value=parse('b');verify.equal(value,'b');cleanup();});" },
    { name: "assertion provenance: named-vitest-assert-assertions-only", filename: TEST_FILE, code: "import {test,assert as verify} from 'vitest';test('a',()=>{verify.equal(value,'a');verify.equal(value,'a');verify.equal(value,'a');});test('b',()=>{verify.equal(value,'b');verify.equal(value,'b');verify.equal(value,'b');});" },
    { name: "assertion provenance: node-strict-alias-different-literal-contract", filename: TEST_FILE, code: "import {test} from 'node:test';import {strict as verify} from 'node:assert';test('a',()=>{const value=parse('a');verify.equal(value,'a');cleanup();});test('b',()=>{const value=parse('b');verify.equal(value,'b');cleanup();});" },
    { name: "assertion provenance: node-strict-alias-assertions-only", filename: TEST_FILE, code: "import {test} from 'node:test';import {strict as verify} from 'node:assert';test('a',()=>{verify.equal(value,'a');verify.equal(value,'a');verify.equal(value,'a');});test('b',()=>{verify.equal(value,'b');verify.equal(value,'b');verify.equal(value,'b');});" },
    { name: "assertion provenance: node-default-assert-different-literal-contract", filename: TEST_FILE, code: "import {test} from 'node:test';import verify from 'node:assert/strict';test('a',()=>{const value=parse('a');verify.equal(value,'a');cleanup();});test('b',()=>{const value=parse('b');verify.equal(value,'b');cleanup();});" },
    { name: "assertion provenance: node-default-assert-assertions-only", filename: TEST_FILE, code: "import {test} from 'node:test';import verify from 'node:assert/strict';test('a',()=>{verify.equal(value,'a');verify.equal(value,'a');verify.equal(value,'a');});test('b',()=>{verify.equal(value,'b');verify.equal(value,'b');verify.equal(value,'b');});" },

    { name: "binding ownership: duplicate-suite-alias", filename: TEST_FILE, code: "import {describe as test} from 'vitest';test('a',()=>{seed('a');run('a');cleanup('a');});test('b',()=>{seed('b');run('b');cleanup('b');});" },
    { name: "binding ownership: duplicate-unrelated", filename: TEST_FILE, code: "import {test} from './model.js';test('a',()=>{seed('a');run('a');cleanup('a');});test('b',()=>{seed('b');run('b');cleanup('b');});" },
    { name: "binding ownership: namespace-runner-outside-contract", filename: TEST_FILE, code: "import * as runner from 'vitest';runner.test('a',()=>{seed('a');run('a');cleanup('a')});runner.test('b',()=>{seed('b');run('b');cleanup('b')});" },

    { name: "does not treat imported describe alias as test", filename: TEST_FILE, code: "import {describe as test} from 'vitest'; test('a', () => {seed('a'); run('a'); cleanup('a');}); test('b', () => {seed('b'); run('b'); cleanup('b');});" },
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
      code: DUPLICATE_TEST_BODY_DOCUMENTATION.examples[0].files[0].source,
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
      name: "ignores generated test paths",
      filename: "/repo/src/generated/user.test.ts",
      code: DUPLICATE_TEST_BODY_DOCUMENTATION.examples[1].files[0].source,
    },
    {
      name: "ignores generated test headers",
      filename: TEST_FILE,
      code: `// @generated\n${DUPLICATE_TEST_BODY_DOCUMENTATION.examples[1].files[0].source}`,
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
    { name: "native named node:assert equal: copied setup", filename: TEST_FILE, code: "import {test} from 'node:test';import {equal as verify} from 'node:assert';test('a',()=>{const result=read('a');verify(result.code, \"same\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"same\"); verify(result.size, 1);});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "native named node:assert strictEqual: copied setup", filename: TEST_FILE, code: "import {test} from 'node:test';import {strictEqual as verify} from 'node:assert';test('a',()=>{const result=read('a');verify(result.code, \"same\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"same\"); verify(result.size, 1);});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "native named node:assert deepEqual: copied setup", filename: TEST_FILE, code: "import {test} from 'node:test';import {deepEqual as verify} from 'node:assert';test('a',()=>{const result=read('a');verify(result.code, \"same\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"same\"); verify(result.size, 1);});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "native named node:assert deepStrictEqual: copied setup", filename: TEST_FILE, code: "import {test} from 'node:test';import {deepStrictEqual as verify} from 'node:assert';test('a',()=>{const result=read('a');verify(result.code, \"same\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"same\"); verify(result.size, 1);});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "native named node:assert ok: copied setup", filename: TEST_FILE, code: "import {test} from 'node:test';import {ok as verify} from 'node:assert';test('a',()=>{const result=read('a');verify(result.code === \"same\"); verify(result.size === 1);});test('b',()=>{const result=read('b');verify(result.code === \"same\"); verify(result.size === 1);});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "native named node:assert/strict equal: copied setup", filename: TEST_FILE, code: "import {test} from 'node:test';import {equal as verify} from 'node:assert/strict';test('a',()=>{const result=read('a');verify(result.code, \"same\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"same\"); verify(result.size, 1);});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "native named node:assert/strict strictEqual: copied setup", filename: TEST_FILE, code: "import {test} from 'node:test';import {strictEqual as verify} from 'node:assert/strict';test('a',()=>{const result=read('a');verify(result.code, \"same\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"same\"); verify(result.size, 1);});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "native named node:assert/strict deepEqual: copied setup", filename: TEST_FILE, code: "import {test} from 'node:test';import {deepEqual as verify} from 'node:assert/strict';test('a',()=>{const result=read('a');verify(result.code, \"same\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"same\"); verify(result.size, 1);});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "native named node:assert/strict deepStrictEqual: copied setup", filename: TEST_FILE, code: "import {test} from 'node:test';import {deepStrictEqual as verify} from 'node:assert/strict';test('a',()=>{const result=read('a');verify(result.code, \"same\"); verify(result.size, 1);});test('b',()=>{const result=read('b');verify(result.code, \"same\"); verify(result.size, 1);});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "native named node:assert/strict ok: copied setup", filename: TEST_FILE, code: "import {test} from 'node:test';import {ok as verify} from 'node:assert/strict';test('a',()=>{const result=read('a');verify(result.code === \"same\"); verify(result.size === 1);});test('b',()=>{const result=read('b');verify(result.code === \"same\"); verify(result.size === 1);});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "assertion provenance: named-expect-same-assertion-with-copied-setup", filename: TEST_FILE, code: "import {test,expect as verify} from 'vitest';test('a',()=>{const value=parse('a');verify(value).toBe('same');cleanup();});test('b',()=>{const value=parse('b');verify(value).toBe('same');cleanup();});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "assertion provenance: named-vitest-assert-same-assertion-with-copied-setup", filename: TEST_FILE, code: "import {test,assert as verify} from 'vitest';test('a',()=>{const value=parse('a');verify.equal(value,'same');cleanup();});test('b',()=>{const value=parse('b');verify.equal(value,'same');cleanup();});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "assertion provenance: node-strict-alias-same-assertion-with-copied-setup", filename: TEST_FILE, code: "import {test} from 'node:test';import {strict as verify} from 'node:assert';test('a',()=>{const value=parse('a');verify.equal(value,'same');cleanup();});test('b',()=>{const value=parse('b');verify.equal(value,'same');cleanup();});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "assertion provenance: node-default-assert-same-assertion-with-copied-setup", filename: TEST_FILE, code: "import {test} from 'node:test';import verify from 'node:assert/strict';test('a',()=>{const value=parse('a');verify.equal(value,'same');cleanup();});test('b',()=>{const value=parse('b');verify.equal(value,'same');cleanup();});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "assertion provenance: local-expect-copied-setup", filename: TEST_FILE, code: "import {test} from 'vitest';const expect=(value)=>consume(value);test('a',()=>{expect('a');run('a');cleanup('a');});test('b',()=>{expect('b');run('b');cleanup('b');});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "assertion provenance: local-expect-substantial-copied-local-calls", filename: TEST_FILE, code: "import {test} from 'vitest';const expect=(value)=>consume(value);test('a',()=>{expect('a');expect('a');expect('a');});test('b',()=>{expect('b');expect('b');expect('b');});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "assertion provenance: unrelated-expect-copied-setup", filename: TEST_FILE, code: "import {test} from 'vitest';import {expect} from './application.js';test('a',()=>{expect('a');run('a');cleanup('a');});test('b',()=>{expect('b');run('b');cleanup('b');});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "assertion provenance: unrelated-expect-substantial-copied-local-calls", filename: TEST_FILE, code: "import {test} from 'vitest';import {expect} from './application.js';test('a',()=>{expect('a');expect('a');expect('a');});test('b',()=>{expect('b');expect('b');expect('b');});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "assertion provenance: local-assert-copied-setup", filename: TEST_FILE, code: "import {test} from 'vitest';const assert=(value)=>consume(value);test('a',()=>{assert('a');run('a');cleanup('a');});test('b',()=>{assert('b');run('b');cleanup('b');});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },
    { name: "assertion provenance: local-assert-substantial-copied-local-calls", filename: TEST_FILE, code: "import {test} from 'vitest';const assert=(value)=>consume(value);test('a',()=>{assert('a');assert('a');assert('a');});test('b',()=>{assert('b');assert('b');assert('b');});", errors: [{ messageId: "duplicateTestBody", suggestions: 0 }] },

    { name: "binding ownership: duplicate-original", filename: TEST_FILE, code: "import {test} from 'vitest';test('a',()=>{seed('a');run('a');cleanup('a');});test('b',()=>{seed('b');run('b');cleanup('b');});", errors: [{ messageId: "duplicateTestBody" }] },
    { name: "binding ownership: duplicate-renamed", filename: TEST_FILE, code: "import {test as check} from 'vitest';check('a',()=>{seed('a');run('a');cleanup('a');});check('b',()=>{seed('b');run('b');cleanup('b');});", errors: [{ messageId: "duplicateTestBody" }] },
    { name: "binding ownership: duplicate-node-default", filename: TEST_FILE, code: "import check from 'node:test';check('a',()=>{seed('a');run('a');cleanup('a');});check('b',()=>{seed('b');run('b');cleanup('b');});", errors: [{ messageId: "duplicateTestBody" }] },

    { name: "preserves default node test ownership", filename: TEST_FILE, code: "import test from 'node:test'; test('a', () => {seed('a'); run('a'); cleanup('a');}); test('b', () => {seed('b'); run('b'); cleanup('b');});", errors: [{messageId: "duplicateTestBody"}] },
    {
      name: "reports the later sibling whose body differs only by case literals",
      filename: TEST_FILE,
      code: DUPLICATE_TEST_BODY_DOCUMENTATION.examples[1].files[0].source,
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
