import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-sleep-in-test-body.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

const TEST_FILE = "/repo/src/worker.test.ts";

ruleTester.run("no-sleep-in-test-body", rule, {
  valid: [
    // --- The critical FP guard: a sleep inside a nested helper/fake declared in
    // the test is SIMULATING latency to exercise a timeout path. That is the
    // intended use of a delay in a test and must never fire. ---
    {
      filename: TEST_FILE,
      code: [
        "it('times out a slow upstream', async () => {",
        "  const slowFetch = async () => {",
        "    await new Promise((r) => setTimeout(r, 5000));",
        "    return new Response('late');",
        "  };",
        "  await expect(withTimeout(slowFetch, 100)).rejects.toThrow();",
        "});",
      ].join("\n"),
    },
    {
      filename: TEST_FILE,
      code: [
        "it('cancels in flight work', async () => {",
        "  function hang() { return sleep(1000); }",
        "  await expect(race(hang())).rejects.toThrow();",
        "});",
      ].join("\n"),
    },
    // --- A zero delay is a macrotask yield to flush the event loop, not a guess. ---
    {
      filename: TEST_FILE,
      code: "it('flushes', async () => { await new Promise((r) => setTimeout(r, 0)); });",
    },
    // --- A non-literal delay is a deliberate parameterised wait. ---
    {
      filename: TEST_FILE,
      code: "it('waits the configured backoff', async () => { await sleep(config.backoffMs); });",
    },
    // --- Fake timers are the recommended fix and must stay clean. ---
    {
      filename: TEST_FILE,
      code: [
        "it('retries after the backoff', async () => {",
        "  vi.useFakeTimers();",
        "  const p = retry(fn);",
        "  await vi.advanceTimersByTimeAsync(5000);",
        "  await p;",
        "});",
      ].join("\n"),
    },
    // --- setTimeout used to schedule work under test, not to sleep. ---
    {
      filename: TEST_FILE,
      code: "it('debounces', () => { setTimeout(() => fire(), 100); vi.runAllTimers(); });",
    },
    // --- Production code is out of scope: a real sleep there is a design choice. ---
    {
      filename: "/repo/src/queue-consumer.ts",
      code: "export async function backoff() { await new Promise((r) => setTimeout(r, 250)); }",
    },
    // --- Not a test-case callback (module scope of a test file). ---
    {
      filename: TEST_FILE,
      code: "const warmup = async () => { await sleep(50); };",
    },
    // --- describe body is setup, not a test body. ---
    {
      filename: TEST_FILE,
      code: "describe('suite', () => { const d = () => sleep(10); it('x', () => { d(); }); });",
    },
  ],
  invalid: [
    // The canonical flaky sleep, directly in the test body.
    {
      filename: TEST_FILE,
      code: "it('eventually posts', async () => { await new Promise((r) => setTimeout(r, 50)); expect(posted()).toBe(true); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    // Block-bodied executor spelling.
    {
      filename: TEST_FILE,
      code: "test('eventually posts', async () => { await new Promise((r) => { setTimeout(r, 100); }); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    // A shared sleep helper called with a literal delay.
    {
      filename: TEST_FILE,
      code: "it('eventually posts', async () => { await sleep(200); expect(posted()).toBe(true); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    // `.only` / `.each` variants are still test bodies.
    {
      filename: TEST_FILE,
      code: "it.only('eventually posts', async () => { await delay(10); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      filename: TEST_FILE,
      code: "it.each([1, 2])('case %i', async () => { await sleep(5); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    // Per-test hooks share the flakiness.
    {
      filename: TEST_FILE,
      code: "beforeEach(async () => { await new Promise((r) => setTimeout(r, 25)); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    // `.spec.ts` and `tests/` directories count as test files too.
    {
      filename: "/repo/tests/router.ts",
      code: "it('settles', async () => { await sleep(30); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      filename: "/repo/src/router.spec.tsx",
      code: "it('settles', async () => { await sleep(30); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
  ],
});
