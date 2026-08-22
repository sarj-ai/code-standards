import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_SLEEP_IN_TEST_BODY_DOCUMENTATION } from "../../src/rules/no-sleep-in-test-body.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

const TEST_FILE = "/repo/src/worker.test.ts";

RULE_TESTER.run("no-sleep-in-test-body", rule, {
  valid: [
    { name: "accepts the documented fake timer", filename: NO_SLEEP_IN_TEST_BODY_DOCUMENTATION.examples[0].focusPath, code: NO_SLEEP_IN_TEST_BODY_DOCUMENTATION.examples[0].files[0].source },
    {
      name: "allows a Promise sleep inside a nested latency fake",
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
      name: "allows a helper sleep inside a nested latency fake",
      filename: TEST_FILE,
      code: [
        "it('cancels in flight work', async () => {",
        "  function hang() { return sleep(1000); }",
        "  await expect(race(hang())).rejects.toThrow();",
        "});",
      ].join("\n"),
    },
    {
      name: "allows a timed Promise used as deferred test input",
      filename: TEST_FILE,
      code: "it('renders suspense', async () => { const deferred = new Promise((resolve) => setTimeout(() => resolve('done'), 10)); expect(await render(deferred)).toBe('done'); });",
    },
    {
      name: "allows a helper delay captured as test input",
      filename: TEST_FILE,
      code: "it('races work', async () => { const delayed = sleep(10); expect(await race(delayed, work())).toBe('work'); });",
    },
    {
      name: "allows a zero-delay Promise used to flush the event loop",
      filename: TEST_FILE,
      code: "it('flushes', async () => { await new Promise((r) => setTimeout(r, 0)); });",
    },
    {
      name: "allows a zero-delay helper used to flush the event loop",
      filename: TEST_FILE,
      code: "it('flushes', async () => { await sleep(0); });",
    },
    {
      name: "allows a parameterized helper delay",
      filename: TEST_FILE,
      code: "it('waits the configured backoff', async () => { await sleep(config.backoffMs); });",
    },
    {
      name: "allows a parameterized Promise delay",
      filename: TEST_FILE,
      code: "it('waits the configured backoff', async () => { await new Promise((r) => setTimeout(r, config.backoffMs)); });",
    },
    {
      name: "allows deterministic fake-timer advancement",
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
    {
      name: "allows setTimeout when it is not wrapped as a Promise sleep",
      filename: TEST_FILE,
      code: "it('debounces', () => { setTimeout(() => fire(), 100); vi.runAllTimers(); });",
    },
    {
      name: "ignores Promise sleeps outside test files",
      filename: "/repo/src/queue-consumer.ts",
      code: "export async function backoff() { await new Promise((r) => setTimeout(r, 250)); }",
    },
    {
      name: "ignores helper sleeps outside a test callback",
      filename: TEST_FILE,
      code: "const warmup = async () => { await sleep(50); };",
    },
    {
      name: "ignores helper sleeps reached through a describe-scoped helper",
      filename: TEST_FILE,
      code: "describe('suite', () => { const d = () => sleep(10); it('x', () => { d(); }); });",
    },
  ],
  invalid: [
    { name: "reports the documented fixed sleep", filename: NO_SLEEP_IN_TEST_BODY_DOCUMENTATION.examples[1].focusPath, code: NO_SLEEP_IN_TEST_BODY_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "noSleepInTestBody" }] },
    {
      name: "reports an expression-bodied Promise sleep in an it callback",
      filename: TEST_FILE,
      code: "it('eventually posts', async () => { await new Promise((r) => setTimeout(r, 50)); expect(posted()).toBe(true); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      name: "reports a block-bodied Promise sleep in a test callback",
      filename: TEST_FILE,
      code: "test('eventually posts', async () => { await new Promise((r) => { setTimeout(r, 100); }); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      name: "reports a sleep helper with a fixed delay",
      filename: TEST_FILE,
      code: "it('eventually posts', async () => { await sleep(200); expect(posted()).toBe(true); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      name: "reports a delay helper in an it.only callback",
      filename: TEST_FILE,
      code: "it.only('eventually posts', async () => { await delay(10); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      name: "reports a sleep helper in an it.each callback",
      filename: TEST_FILE,
      code: "it.each([1, 2])('case %i', async () => { await sleep(5); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      name: "reports a Promise sleep in a beforeEach hook",
      filename: TEST_FILE,
      code: "beforeEach(async () => { await new Promise((r) => setTimeout(r, 25)); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      name: "reports a helper sleep in a tests directory",
      filename: "/repo/tests/router.ts",
      code: "it('settles', async () => { await sleep(30); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      name: "reports a helper sleep in a spec.tsx file",
      filename: "/repo/src/router.spec.tsx",
      code: "it('settles', async () => { await sleep(30); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      name: "reports wait and pause helpers with fixed delays",
      filename: TEST_FILE,
      code: "test('settles', async () => { await wait(10); await pause(20); });",
      errors: [
        { messageId: "noSleepInTestBody" },
        { messageId: "noSleepInTestBody" },
      ],
    },
    {
      name: "reports a Promise sleep with a function executor",
      filename: TEST_FILE,
      code: "test('settles', async () => { await new Promise(function (resolve) { setTimeout(resolve, 10); }); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      name: "reports a Promise sleep returned directly by a test",
      filename: TEST_FILE,
      code: "test('settles', () => new Promise((resolve) => setTimeout(resolve, 10)));",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      name: "reports a helper sleep in a test.skip callback",
      filename: TEST_FILE,
      code: "test.skip('settles', async () => { await sleep(10); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      name: "reports a helper sleep in a tagged test.each callback",
      filename: TEST_FILE,
      code: "test.each`value\n${1}`('case', async () => { await sleep(10); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      name: "reports a helper sleep in an afterEach hook",
      filename: TEST_FILE,
      code: "afterEach(async () => { await sleep(10); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
    {
      name: "reports a helper sleep in a traditional function test callback",
      filename: TEST_FILE,
      code: "test('settles', async function () { await sleep(10); });",
      errors: [{ messageId: "noSleepInTestBody" }],
    },
  ],
});
