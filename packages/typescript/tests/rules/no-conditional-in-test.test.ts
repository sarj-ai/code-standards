import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-conditional-in-test.js";

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

ruleTester.run("no-conditional-in-test", rule, {
  valid: [
    {
      filename: TEST_FILE,
      code: "it('works without conditionals', () => { expect(1).toBe(1); });",
    },
    {
      filename: TEST_FILE,
      code: "test('works without conditionals', () => { const a = 1; expect(a).toBe(1); });",
    },
    {
      filename: TEST_FILE,
      code: "it('allows conditionals in helper functions', () => { const helper = (b) => { if (b) return 1; return 2; }; expect(helper(true)).toBe(1); });",
    },
    {
      filename: "/repo/src/component.ts",
      code: "export function comp(a) { if (a) { return true; } return false; }",
    },
    {
      filename: TEST_FILE,
      code: "describe('suite', () => { if (process.env.CI) { it('runs', () => { expect(true).toBe(true); }); } });",
    },

    // --- Guard 1: narrowing guard pinned by the assertion above it ---
    // The `if` is a tax paid to the type checker. Had `success` gone the other
    // way, the preceding `expect` would already have failed the test, so the
    // guarded assertions cannot be silently skipped.
    {
      filename: TEST_FILE,
      code: `test('returns errors from both union arms', () => {
        const result = union.safeParse('a');
        expect(result.success).toEqual(false);
        if (!result.success) {
          expect(result.error.issues).toHaveLength(2);
        }
      });`,
    },
    // Same shape through a member chain and an equality test.
    {
      filename: TEST_FILE,
      code: `test('rejects an unauthenticated request', async () => {
        const res = await authenticateRequest(request);
        expect(res.ok).toBe(false);
        if (res.ok === false) {
          expect(res.error.type).toBe('unauthorized');
        }
      });`,
    },

    // --- Guard 2: an assertion spelled as a throwing guard ---
    {
      filename: TEST_FILE,
      code: `test('fetches the atlassian status page', async () => {
        const fetcher = allFetchers.find((f) => f.name === 'atlassian');
        if (!fetcher) throw new Error('atlassian fetcher missing');
        const result = await fetcher.fetch(entry);
        expect(result).toHaveProperty('severity');
      });`,
    },
    {
      filename: TEST_FILE,
      code: `test('streams an error event', async () => {
        const res = await streamSSE(c, handler, onError);
        if (!res.body) {
          throw new Error('Body is null');
        }
        expect(onError).toBeCalledTimes(1);
      });`,
    },

    // --- Guard 3: `??` / `||` defaults are values, not control flow ---
    {
      filename: TEST_FILE,
      code: "test('lists monitors', () => { const monitors = data.httpMonitors || []; expect(monitors).toHaveLength(0); });",
    },
    {
      filename: TEST_FILE,
      code: "test('reads the code', () => { const code = res.code ?? ''; expect(code).toBe(''); });",
    },
    // A `||` in statement position whose right side asserts nothing is setup,
    // not a gated assertion.
    {
      filename: TEST_FILE,
      code: "test('warms the cache once', () => { warmed || warmCache(); expect(cache.size).toBe(1); });",
    },

    // --- Guard 4: narrowing around assertions erased at run time ---
    {
      filename: TEST_FILE,
      code: `test('types the response by status', async () => {
        const res = await client.index.$get();
        if (res.status === 200) {
          expectTypeOf(await res.json()).toEqualTypeOf<{ 200: true }>();
        }
        if (res.status === 400) {
          expectTypeOf(await res.json()).toEqualTypeOf<{ 400: true }>();
        }
      });`,
    },

    // --- Guard 5: state normalization with no assertion and no escape ---
    {
      filename: TEST_FILE,
      code: `test('redacts the stack before snapshotting', async () => {
        const json = await res.json();
        if (json.error.data.stack) {
          json.error.data.stack = '[redacted]';
        }
        expect(json).toMatchInlineSnapshot();
      });`,
    },
  ],
  invalid: [
    {
      filename: TEST_FILE,
      code: "it('fails with if', () => { if (true) { expect(1).toBe(1); } });",
      errors: [{ messageId: "noConditionalInTest" }],
    },
    {
      filename: TEST_FILE,
      code: "test('fails with switch', () => { switch (a) { case 1: expect(1).toBe(1); } });",
      errors: [{ messageId: "noConditionalInTest" }],
    },
    {
      filename: TEST_FILE,
      code: "it('fails with ternary', () => { const a = b ? 1 : 2; expect(a).toBe(1); });",
      errors: [{ messageId: "noConditionalInTest" }],
    },
    {
      filename: TEST_FILE,
      code: "it('fails with logical expression', () => { a && expect(a).toBe(1); });",
      errors: [{ messageId: "noConditionalInTest" }],
    },
    {
      filename: TEST_FILE,
      code: "it.only('fails on variants', () => { if (a) { expect(a).toBe(1); } });",
      errors: [{ messageId: "noConditionalInTest" }],
    },

    // --- Upper bounds on guard 1 ---
    // UNPINNED narrowing guard: nothing above establishes which way the
    // discriminant went, so when the parse unexpectedly succeeds the whole test
    // passes having asserted nothing.
    {
      filename: TEST_FILE,
      code: `test('reports the transform issue', () => {
        const arg = foo.safeParse(undefined);
        if (!arg.success) {
          expect(arg.error.issues[0].message).toEqual('bad');
        }
      });`,
      errors: [{ messageId: "noConditionalInTest" }],
    },
    // The preceding assertion is about a DIFFERENT value, so it pins nothing.
    {
      filename: TEST_FILE,
      code: `test('does not pin across values', () => {
        expect(other.success).toBe(false);
        if (!result.success) {
          expect(result.error).toBeDefined();
        }
      });`,
      errors: [{ messageId: "noConditionalInTest" }],
    },

    // --- Upper bounds on guard 2 ---
    // A throwing consequent with an `else` is a real two-way branch, and the
    // assertions in the `else` really can be skipped.
    {
      filename: TEST_FILE,
      code: `test('branches on the result', () => {
        if (!value) {
          throw new Error('missing');
        } else {
          expect(value).toBe(1);
        }
      });`,
      errors: [{ messageId: "noConditionalInTest" }],
    },

    // --- Upper bounds on guard 4 ---
    // A run-time assertion mixed in with the type-level one is skippable.
    {
      filename: TEST_FILE,
      code: `test('mixes runtime and type assertions', async () => {
        const res = await client.index.$get();
        if (res.status === 200) {
          expectTypeOf(res).toEqualTypeOf<Ok>();
          expect(res.ok).toBe(true);
        }
      });`,
      errors: [{ messageId: "noConditionalInTest" }],
    },

    // --- Upper bounds on guard 5: the rule's best true positives ---
    // A branch that RETURNS out of the test. The test reports success having
    // asserted nothing whenever the dependency is unavailable.
    {
      filename: TEST_FILE,
      code: `test('graceful degradation when operations fail', async () => {
        if (!isRedisAvailable) {
          logger.info('Skipping test: Redis not available');
          return;
        }
        const result = await cacheService.set('k', 1);
        expect(result.ok).toBe(true);
      });`,
      errors: [{ messageId: "noConditionalInTest" }],
    },
    // The same escape without a block. Upstream annotates this shape
    // "FIXME: This should be consistent or skip the whole test".
    {
      filename: TEST_FILE,
      code: `test('reschedules to a video call', async () => {
        const locationVideoCallUrl = parse(booking.metadata)?.videoCallUrl;
        if (!locationVideoCallUrl) return;
        expect(locationVideoCallUrl).not.toBeUndefined();
      });`,
      errors: [{ messageId: "noConditionalInTest" }],
    },
    // A conditional skip is the canonical true positive and must keep firing.
    {
      filename: TEST_FILE,
      code: `test('hits the live API', async () => {
        if (!process.env.API_TOKEN) {
          test.skip();
        }
        expect(await call()).toBe('ok');
      });`,
      errors: [{ messageId: "noConditionalInTest" }],
    },
    // A `continue` inside a loop skips the assertions for that iteration.
    {
      filename: TEST_FILE,
      code: `test('checks every row', () => {
        for (const row of rows) {
          if (!row.enabled) {
            continue;
          }
          expect(row.value).toBeGreaterThan(0);
        }
      });`,
      errors: [{ messageId: "noConditionalInTest" }],
    },
  ],
});
