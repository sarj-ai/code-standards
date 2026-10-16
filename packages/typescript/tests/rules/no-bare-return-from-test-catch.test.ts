// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION } from "../../src/rules/no-bare-return-from-test-catch.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });
const TEST_FILE = "/repo/src/codec.test.ts";

RULE_TESTER.run("no-bare-return-from-test-catch", rule, {
  valid: [
    ...([
      ["for context skip", "test.for([1])('optional', (value, context) => { try { run(value); } catch { context.skip();return; } expect(done).toBe(true); });"],
      ["for destructured skip alias", "test.for([1])('optional', (value, {skip: skipCase}) => { try { run(value); } catch { skipCase('unavailable');return; } expect(done).toBe(true); });"],
      ["ordinary test context skip", "test('optional', (context) => { try { run(); } catch { context.skip();return; } expect(done).toBe(true); });"],
      ["ordinary destructured context skip", "test('optional', ({skip}) => { try { run(); } catch { skip();return; } expect(done).toBe(true); });"],
      ["unrelated context state remains mutable", "test.for([1])('optional', (value, context) => { context.note = 'probe'; try { run(value); } catch { context.skip();return; } expect(done).toBe(true); });"],
      ["literal true skip condition", "test.for([1])('optional', (value, context) => { try { run(value); } catch { context.skip(true, reason);return; } expect(done).toBe(true); });"],
      ["static template skip note", "test.for([1])('optional', (value, {skip}) => { try { run(value); } catch { skip(`unavailable`);return; } expect(done).toBe(true); });"],
      ["for tagged table and registration options", "test.concurrent.for`value\n${1}`('optional', {timeout: 100}, (value, context) => { try { run(value); } catch { context['skip']('unavailable');return; } expect(done).toBe(true); });"],
      ["conditional runner retains ordinary context position", "test.runIf(enabled)('optional', ({skip}) => { try { run(); } catch { skip();return; } expect(done).toBe(true); });"],
      ["adjacent caught-error assertion in table", "test.for([1])('rejects', () => { try { run(); } catch (error) { expect(error).toBeInstanceOf(Error);return; } expect.fail('must reject'); });"],
    ] as const).map(([name, body]) => ({name, filename: TEST_FILE, code: `import {test, expect} from 'vitest'; ${body}`})),
    { name: "global table runner supports context skip", filename: TEST_FILE, code: "test.for([1])('optional', (value, context) => { try { run(value); } catch { context.skip();return; } expect(done).toBe(true); });" },
    { name: "configured global runner supports destructured skip", filename: TEST_FILE, languageOptions: {globals: {test: 'readonly'}}, code: "test('optional', ({skip}) => { try { run(); } catch { skip();return; } expect(done).toBe(true); });" },
    { name: "renamed Vitest test preserves context ownership", filename: TEST_FILE, code: "import {test as check, expect} from 'vitest'; check.for([1])('optional', (value, {skip: skipCase}) => { try { run(value); } catch { skipCase();return; } expect(done).toBe(true); });" },
    { name: "preserves exact-code explained suppression for an optional table case", filename: TEST_FILE, code: "test.each([1])('optional', () => { try { run(); } catch {\n// eslint-disable-next-line @rule-tester/no-bare-return-from-test-catch -- capability probe intentionally abandons the optional case\nreturn; } expect(done).toBe(true); });" },
    { name: "parameterized expected error remains observed", filename: TEST_FILE, code: "test.each([1, 2])('rejects %s', (value) => { try { run(value); } catch (error) { expect(error).toBeInstanceOf(Error); return; } expect.fail('must reject'); });" },
    { name: "parameterized explicit skip remains valid", filename: TEST_FILE, code: "test.each([1, 2])('optional %s', (value) => { try { run(value); } catch { test.skip(); return; } expect(done).toBe(true); });" },
    { name: "parameterized rethrow preserves failure", filename: TEST_FILE, code: "test.for([1, 2])('runs %s', (value) => { try { run(value); } catch (error) { throw error; } expect(done).toBe(true); });" },
    { name: "builder inputs are not test callbacks", filename: TEST_FILE, code: "test.each(() => { try { run(); } catch { return; } expect(done).toBe(true); });" },
    { name: "custom builder has no proved runner contract", filename: TEST_FILE, code: "test.custom(cases)('runs', () => { try { run(); } catch { return; } expect(done).toBe(true); });" },
    { name: "unknown tag has no proved runner contract", filename: TEST_FILE, code: "test.custom`value`('runs', () => { try { run(); } catch { return; } expect(done).toBe(true); });" },
    { name: "dynamic builder has no proved runner contract", filename: TEST_FILE, code: "test[builder](cases)('runs', () => { try { run(); } catch { return; } expect(done).toBe(true); });" },
    { name: "shadowed imported table runner remains custom", filename: TEST_FILE, code: "import {test} from 'vitest'; function check(test) { test.each([1])('runs', () => { try { run(); } catch { return; } expect(done).toBe(true); }); }" },
    { name: "nested table callback return does not exit test", filename: TEST_FILE, code: "test.each([1])('runs', () => { try { run(); } catch { values.forEach(() => { return; }); } expect(done).toBe(true); });" },
    { name: "binding ownership: catch-local", filename: TEST_FILE, code: "function test(n:string,f:()=>unknown){return f;} test('case',()=>{try{run();}catch{return;}expect(done).toBe(true);});" },
    { name: "binding ownership: catch-local-assertion", filename: TEST_FILE, code: "import {test} from 'vitest';function expect(v:unknown){return {toBe(v:unknown){return true}}}test('case',()=>{try{run();}catch{return;}expect(done).toBe(true);});" },
    { name: "binding ownership: type-erased-assertion-abstention", filename: TEST_FILE, code: "import {test} from 'vitest';import type {expect} from 'vitest';test('case',()=>{try{run()}catch{return;}expect(done).toBe(true)});" },

    { name: "preserves negated caught-error assertion", filename: TEST_FILE, code: "test('rejects', () => { try { run(); } catch (error) { expect(error).not.toBeNull(); return; } expect.fail('must reject'); });" },
    { name: "preserves asserted rejection return", filename: TEST_FILE, code: "test('rejects', () => { try { run(); } catch (error) { expect(error).toBeInstanceOf(Error); return; } expect.fail('must reject'); });" },
    { name: "preserves imported assertion alias", filename: TEST_FILE, code: "import {expect as verify} from 'vitest'; test('rejects', () => { try { run(); } catch (error) { verify(error.message).toBe('bad'); return; } verify.fail('must reject'); });" },
    { name: "preserves default node assert on the caught error", filename: TEST_FILE, code: "import verify from 'node:assert/strict'; test('rejects', () => { try { run(); } catch (error) { verify(error); return; } verify.fail('must reject'); });" },
    { name: "preserves namespace node assert on the caught error", filename: TEST_FILE, code: "import * as verify from 'node:assert/strict'; test('rejects', () => { try { run(); } catch (error) { verify.ok(error); return; } verify.fail('must reject'); });" },
    { name: "preserves a caught-error assertion in the return's nested block", filename: TEST_FILE, code: "test('rejects', () => { try { run(); } catch (error) { if (optional) { expect(error).toBeDefined(); return; } } expect.fail('must reject'); });" },
    { name: "public no-match example", filename: NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION.examples[0].focusPath, code: NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION.examples[0].files[0].source },
    { name: "requires a later assertion", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch { return; } cleanup(); });" },
    { name: "allows returned values", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch { return fallback; } expect(done).toBe(true); });" },
    { name: "allows explicit runner skip", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch { test.skip(); return; } expect(done).toBe(true); });" },
    { name: "allows an explicit runner skip in the return's nested block", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch { if (optional) { test.skip(); return; } } expect(done).toBe(true); });" },
    { name: "ignores nested callbacks", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch { values.forEach(() => { return; }); } expect(done).toBe(true); });" },
    { name: "ignores helper functions", filename: TEST_FILE, code: "function helper() { try { run(); } catch { return; } } test('x', () => { helper(); expect(done).toBe(true); });" },
    { name: "ignores an assertion inside a later nested callback", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch { return; } later(() => expect(done).toBe(true)); });" },
    { name: "ignores local runner and assertion bindings", filename: TEST_FILE, code: "const test = (_n, f) => f(); const expect = (x) => x; test('x', () => { try { run(); } catch { return; } expect(done).toBe(true); });" },
    { name: "ignores unsupported imports", filename: TEST_FILE, code: "import { test, expect } from './helpers'; test('x', () => { try { run(); } catch { return; } expect(done).toBe(true); });" },
    { name: "ignores production files", filename: "/repo/src/codec.ts", code: "test('x', () => { try { run(); } catch { return; } expect(done).toBe(true); });" },
    { name: "ignores generated paths", filename: "/repo/generated/codec.test.ts", code: "test('x', () => { try { run(); } catch { return; } expect(done).toBe(true); });" },
    { name: "ignores generated headers", filename: TEST_FILE, code: "// @generated\ntest('x', () => { try { run(); } catch { return; } expect(done).toBe(true); });" },
  ],
  invalid: [
    ...([
      ["false skip condition", "test.for([1])('optional', (value, context) => { try { run(value); } catch { context.skip(false);return; } expect(done).toBe(true); });"],
      ["unknown skip condition", "test.for([1])('optional', (value, {skip}) => { try { run(value); } catch { skip(optional);return; } expect(done).toBe(true); });"],
      ["conditional context skip", "test.for([1])('optional', (value, context) => { try { run(value); } catch { if (optional) context.skip();return; } expect(done).toBe(true); });"],
      ["for first argument is case data", "test.for([{skip: custom}])('optional', (context) => { try { run(); } catch { context.skip();return; } expect(done).toBe(true); });"],
      ["each second argument is case data", "test.each([[1, {skip: custom}]])('optional', (value, context) => { try { run(value); } catch { context.skip();return; } expect(done).toBe(true); });"],
      ["each destructured argument is case data", "test.each([{skip: custom}])('optional', ({skip}) => { try { run(); } catch { skip();return; } expect(done).toBe(true); });"],
      ["reassigned context", "test.for([1])('optional', (value, context) => { context = custom; try { run(value); } catch { context.skip();return; } expect(done).toBe(true); });"],
      ["overwritten context method", "test.for([1])('optional', (value, context) => { context.skip = custom; try { run(value); } catch { context.skip();return; } expect(done).toBe(true); });"],
      ["deleted context method", "test.for([1])('optional', (value, context) => { delete context.skip; try { run(value); } catch { context.skip();return; } expect(done).toBe(true); });"],
      ["reassigned destructured skip", "test.for([1])('optional', (value, {skip}) => { skip = custom; try { run(value); } catch { skip();return; } expect(done).toBe(true); });"],
      ["shadowed context", "test.for([1])('optional', (value, context) => { try { run(value); } catch { const context = custom; context.skip();return; } expect(done).toBe(true); });"],
      ["shadowed destructured skip", "test.for([1])('optional', (value, {skip}) => { try { run(value); } catch { const skip = custom; skip();return; } expect(done).toBe(true); });"],
    ] as const).map(([name, body]) => ({name, filename: TEST_FILE, code: `import {test, expect} from 'vitest'; ${body}`, errors: [{messageId: "bareReturnFromTestCatch" as const}]})),
    { name: "foreign runner does not establish Vitest context", filename: TEST_FILE, code: "import {test, expect} from '@jest/globals'; test.for([1])('optional', (value, context) => { try { run(value); } catch { context.skip();return; } expect(done).toBe(true); });", errors: [{messageId: "bareReturnFromTestCatch"}] },
    { name: "case table preserves the later assertion obligation", filename: TEST_FILE, code: "test.each([1, 2])('runs %s', (value) => { try { run(value); } catch { return; } expect(done).toBe(true); });", errors: [{ messageId: "bareReturnFromTestCatch" }] },
    { name: "for table preserves the later assertion obligation", filename: TEST_FILE, code: "test.for([1, 2])('runs %s', (value) => { try { run(value); } catch { return; } expect(done).toBe(true); });", errors: [{ messageId: "bareReturnFromTestCatch" }] },
    { name: "conditional runner builder preserves failure", filename: TEST_FILE, code: "test.runIf(enabled)('runs', () => { try { run(); } catch { return; } expect(done).toBe(true); });", errors: [{ messageId: "bareReturnFromTestCatch" }] },
    { name: "skipIf builder does not skip caught failures", filename: TEST_FILE, code: "test.skipIf(unavailable)('runs', () => { try { run(); } catch { return; } expect(done).toBe(true); });", errors: [{ messageId: "bareReturnFromTestCatch" }] },
    { name: "chained builders and modifiers retain callback ownership", filename: TEST_FILE, code: "import {test as check, expect as verify} from 'vitest'; check.runIf(enabled).concurrent.each([1])('runs', () => { try { run(); } catch { return; } verify(done).toBe(true); });", errors: [{ messageId: "bareReturnFromTestCatch" }] },
    { name: "tagged each table retains callback ownership", filename: TEST_FILE, code: "test.each`value | expected\n${1} | ${true}`('runs', () => { try { run(); } catch { return; } expect(done).toBe(true); });", errors: [{ messageId: "bareReturnFromTestCatch" }] },
    { name: "tagged for table retains callback ownership", filename: TEST_FILE, code: "test.for`value | expected\n${1} | ${true}`('runs', () => { try { run(); } catch { return; } expect(done).toBe(true); });", errors: [{ messageId: "bareReturnFromTestCatch" }] },
    { name: "erased table builder and callback retain ownership", filename: TEST_FILE, code: "(test.each([1]) as typeof test)('runs', (() => { try { run(); } catch { return; } expect(done).toBe(true); }) satisfies () => void);", errors: [{ messageId: "bareReturnFromTestCatch" }] },
    { name: "binding ownership: catch-renamed", filename: TEST_FILE, code: "import {test as check,expect as verify} from 'vitest';check('case',()=>{try{run();}catch{return;}verify(done).toBe(true);});", errors: [{ messageId: "bareReturnFromTestCatch" }] },
    { name: "binding ownership: catch-node-default", filename: TEST_FILE, code: "import check from 'node:test';import assert from 'node:assert/strict';check('case',()=>{try{run();}catch{return;}assert.equal(done,true);});", errors: [{ messageId: "bareReturnFromTestCatch" }] },

    { name: "property name is not caught error reference", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch (error) { expect(result.error).toBe(true); return; } expect(done).toBe(true); });", errors: [{messageId: "bareReturnFromTestCatch"}] },
    { name: "bare expect construction is not assertion", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch (error) { expect(error); return; } expect(done).toBe(true); });", errors: [{messageId: "bareReturnFromTestCatch"}] },
    { name: "unrelated assertion does not validate error", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch (error) { expect(true).toBe(true); return; } expect(done).toBe(true); });", errors: [{messageId: "bareReturnFromTestCatch"}] },
    { name: "conditional assertion does not dominate return", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch (error) { if (flag) expect(error).toBeDefined(); return; } expect(done).toBe(true); });", errors: [{messageId: "bareReturnFromTestCatch"}] },
    { name: "conditional throw does not protect the return path", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch (error) { if (fatal) throw error; return; } expect(done).toBe(true); });", errors: [{messageId: "bareReturnFromTestCatch"}] },
    { name: "conditional skip does not dominate the return", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch { if (optional) test.skip(); return; } expect(done).toBe(true); });", errors: [{messageId: "bareReturnFromTestCatch"}] },
    { name: "finally cleanup does not protect a skipped assertion", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch { return; } finally { cleanup(); } expect(done).toBe(true); });", errors: [{messageId: "bareReturnFromTestCatch"}] },
    { name: "public match example", filename: NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION.examples[1].focusPath, code: NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "bareReturnFromTestCatch", type: "ReturnStatement" }] },
    { name: "supports imported aliases and modifiers", filename: TEST_FILE, code: "import { test as check, expect as verify } from 'vitest'; check.only('x', () => { try { run(); } catch { return; } verify(done).toBe(true); });", errors: [{ messageId: "bareReturnFromTestCatch" }] },
    { name: "supports assertions nested in later control flow", filename: TEST_FILE, code: "it('x', () => { try { run(); } catch { if (optional) return; } if (ready) { expect(done).toBe(true); } });", errors: [{ messageId: "bareReturnFromTestCatch" }] },
    { name: "supports node assert", filename: TEST_FILE, code: "import { test } from 'node:test'; import { strict as verify } from 'node:assert'; test('x', () => { try { run(); } catch { return; } verify.equal(done, true); });", errors: [{ messageId: "bareReturnFromTestCatch" }] },
  ],
});
