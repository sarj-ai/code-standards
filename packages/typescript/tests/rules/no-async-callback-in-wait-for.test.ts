import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  noAsyncCallbackInWaitForDocumentation,
} from "../../src/rules/no-async-callback-in-wait-for.js";

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

ruleTester.run("no-async-callback-in-wait-for", rule, {
  valid: [
    {
      name: "allows a synchronous arrow callback",
      filename: TEST_FILE,
      code: noAsyncCallbackInWaitForDocumentation.examples[0].files[0].source,
    },
    {
      name: "allows a synchronous function-expression callback",
      filename: TEST_FILE,
      code: "it('works', async () => { await waitFor(function() { expect(foo).toBe(true); }); });",
    },
    {
      name: "ignores async callbacks passed to other functions",
      filename: TEST_FILE,
      code: "it('works', async () => { await doSomething(async () => { expect(foo).toBe(true); }); });",
    },
    {
      name: "ignores bare waitFor calls in production files",
      filename: "/repo/src/production.ts",
      code: "async function fetch() { return waitFor(async () => {}); }",
    },
    {
      name: "allows a synchronous callback in member-form waitFor",
      filename: TEST_FILE,
      code: "it('works', async () => { await vi.waitFor(() => expect(foo).toBe(true)); });",
    },
    {
      name: "ignores member methods whose names only start with waitFor",
      filename: TEST_FILE,
      code: "it('works', async () => { await page.waitForSelector(async () => {}); });",
    },
    {
      name: "ignores computed waitFor member calls",
      filename: TEST_FILE,
      code: "it('works', async () => { await api['waitFor'](async () => {}); });",
    },
    {
      name: "ignores member-form waitFor calls in production files",
      filename: "/repo/src/production.ts",
      code: "async function poll() { return vi.waitFor(async () => {}); }",
    },
    {
      name: "ignores a non-function first argument",
      filename: TEST_FILE,
      code: "it('works', async () => { const pending = Promise.resolve(); await waitFor(pending); });",
    },
    {
      name: "does not follow a function passed by reference",
      filename: TEST_FILE,
      code: "it('works', async () => { const check = async () => true; await waitFor(check); });",
    },
    {
      name: "checks only the first argument",
      filename: TEST_FILE,
      code: "it('works', async () => { await waitFor(() => true, async () => false); });",
    },
  ],
  invalid: [
    {
      name: "reports an async arrow callback even without await",
      filename: TEST_FILE,
      code: noAsyncCallbackInWaitForDocumentation.examples[1].files[0].source,
      errors: [{ messageId: "noAsyncCallbackInWaitFor" }],
    },
    {
      name: "reports an async function-expression callback",
      filename: TEST_FILE,
      code: "it('fails', async () => { await waitFor(async function() { expect(foo).toBe(true); }); });",
      errors: [{ messageId: "noAsyncCallbackInWaitFor" }],
    },
    {
      name: "reports an async callback in vi.waitFor",
      filename: TEST_FILE,
      code: "it('fails', async () => { await vi.waitFor(async () => expect(foo).toBe(true)); });",
      errors: [{ messageId: "noAsyncCallbackInWaitFor" }],
    },
    {
      name: "reports an async function expression in member-form waitFor",
      filename: TEST_FILE,
      code: "it('fails', async () => { await screen.waitFor(async function() { expect(foo).toBe(true); }); });",
      errors: [{ messageId: "noAsyncCallbackInWaitFor" }],
    },
    {
      name: "reports an async callback on a deeply nested receiver",
      filename: TEST_FILE,
      code: "it('fails', async () => { await testing.utils.waitFor(async () => { expect(foo).toBe(true); }); });",
      errors: [{ messageId: "noAsyncCallbackInWaitFor" }],
    },
  ],
});
