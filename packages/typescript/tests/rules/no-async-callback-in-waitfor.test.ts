import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-async-callback-in-waitfor.js";

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

ruleTester.run("no-async-callback-in-waitfor", rule, {
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
    }
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
    }
  ],
});
