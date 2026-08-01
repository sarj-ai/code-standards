import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-async-callback-in-wait-for.js";

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
      filename: TEST_FILE,
      code: "it('works', async () => { await waitFor(() => expect(foo).toBe(true)); });",
    },
    {
      filename: TEST_FILE,
      code: "it('works', async () => { await waitFor(function() { expect(foo).toBe(true); }); });",
    },
    {
      // Not waitFor
      filename: TEST_FILE,
      code: "it('works', async () => { await doSomething(async () => { expect(foo).toBe(true); }); });",
    },
    {
      // Production file
      filename: "/repo/src/production.ts",
      code: "async function fetch() { return waitFor(async () => {}); }",
    },
    {
      // Member form, synchronous callback — the shape the rule asks for.
      filename: TEST_FILE,
      code: "it('works', async () => { await vi.waitFor(() => expect(foo).toBe(true)); });",
    },
    {
      // A member call that merely ends in something else. `waitForSelector` and
      // `waitForTimeout` take no polled assertion callback at all.
      filename: TEST_FILE,
      code: "it('works', async () => { await page.waitForSelector(async () => {}); });",
    },
    {
      // A computed member is not statically `waitFor`.
      filename: TEST_FILE,
      code: "it('works', async () => { await api['waitFor'](async () => {}); });",
    },
    {
      // Member form in a production file stays exempt, like the bare form.
      filename: "/repo/src/production.ts",
      code: "async function poll() { return vi.waitFor(async () => {}); }",
    },
  ],
  invalid: [
    {
      filename: TEST_FILE,
      code: "it('fails', async () => { await waitFor(async () => expect(foo).toBe(true)); });",
      errors: [{ messageId: "noAsyncCallbackInWaitFor" }],
    },
    {
      filename: TEST_FILE,
      code: "it('fails', async () => { await waitFor(async function() { expect(foo).toBe(true); }); });",
      errors: [{ messageId: "noAsyncCallbackInWaitFor" }],
    },
    {
      // `vi.waitFor` — the member form the rule could not see at all. This case is
      // the regression: it reported 0 messages before the callee check was widened.
      filename: TEST_FILE,
      code: "it('fails', async () => { await vi.waitFor(async () => expect(foo).toBe(true)); });",
      errors: [{ messageId: "noAsyncCallbackInWaitFor" }],
    },
    {
      filename: TEST_FILE,
      code: "it('fails', async () => { await screen.waitFor(async function() { expect(foo).toBe(true); }); });",
      errors: [{ messageId: "noAsyncCallbackInWaitFor" }],
    },
    {
      // Deep member chains resolve on the property name, not the receiver shape.
      filename: TEST_FILE,
      code: "it('fails', async () => { await testing.utils.waitFor(async () => { expect(foo).toBe(true); }); });",
      errors: [{ messageId: "noAsyncCallbackInWaitFor" }],
    },
  ],
});
