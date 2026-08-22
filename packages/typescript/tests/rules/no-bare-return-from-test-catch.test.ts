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
    { name: "public no-match example", filename: NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION.examples[0].focusPath, code: NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION.examples[0].files[0].source },
    { name: "requires a later assertion", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch { return; } cleanup(); });" },
    { name: "allows returned values", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch { return fallback; } expect(done).toBe(true); });" },
    { name: "allows rethrow in catch", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch (error) { if (fatal) throw error; return; } expect(done).toBe(true); });" },
    { name: "allows explicit runner skip", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch { test.skip(); return; } expect(done).toBe(true); });" },
    { name: "allows finally cleanup", filename: TEST_FILE, code: "test('x', () => { try { run(); } catch { return; } finally { cleanup(); } expect(done).toBe(true); });" },
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
    { name: "public match example", filename: NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION.examples[1].focusPath, code: NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "bareReturnFromTestCatch", type: "ReturnStatement" }] },
    { name: "supports imported aliases and modifiers", filename: TEST_FILE, code: "import { test as check, expect as verify } from 'vitest'; check.only('x', () => { try { run(); } catch { return; } verify(done).toBe(true); });", errors: [{ messageId: "bareReturnFromTestCatch" }] },
    { name: "supports assertions nested in later control flow", filename: TEST_FILE, code: "it('x', () => { try { run(); } catch { if (optional) return; } if (ready) { expect(done).toBe(true); } });", errors: [{ messageId: "bareReturnFromTestCatch" }] },
    { name: "supports node assert", filename: TEST_FILE, code: "import { test } from 'node:test'; import { strict as verify } from 'node:assert'; test('x', () => { try { run(); } catch { return; } verify.equal(done, true); });", errors: [{ messageId: "bareReturnFromTestCatch" }] },
  ],
});
