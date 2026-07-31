import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-hand-rolled-sleep.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

/** A server-side module path: not a test, not a script, not generated, not JSX. */
const SERVER = "/repo/src/lib/queue.ts";

ruleTester.run("no-hand-rolled-sleep", rule, {
  valid: [
    // ---- The fix itself must not be flagged. ----
    {
      code: `import { setTimeout as sleep } from "node:timers/promises";
             await sleep(500, undefined, { signal });`,
      filename: SERVER,
    },
    {
      code: `const signal = AbortSignal.timeout(5000);
             await work({ signal });`,
      filename: SERVER,
    },

    // ---- `setTimeout(resolve, 0)` is a macrotask yield, not a delay. The
    // stdlib answer is `setImmediate`, a different fix. ----
    {
      code: "await new Promise((resolve) => setTimeout(resolve, 0));",
      filename: SERVER,
    },
    {
      code: "await new Promise((resolve) => { setTimeout(resolve, 0); });",
      filename: SERVER,
    },

    // ---- A delayed VALUE is not a sleep. Every corpus occurrence of this
    // shape was the losing arm of a race that resolves to a fallback result,
    // which `node:timers/promises` does not express. ----
    {
      code: "await new Promise((resolve) => setTimeout(() => resolve(fallback), 4000));",
      filename: SERVER,
    },
    {
      code: "await new Promise((resolve) => setTimeout(() => { resolve(fallback); }, 4000));",
      filename: SERVER,
    },

    // ---- Already cancellable: the executor does more than the one call, so
    // the handle is captured for `clearTimeout` or an abort listener is wired.
    // Reporting these would be backwards — they are what the rule asks for.
    // This guard is load bearing: in the OSS corpus every reject-flavoured arm
    // that this rule does NOT report captures its handle exactly this way. ----
    {
      code: `await new Promise((resolve) => {
               const timer = setTimeout(resolve, ms);
               signal.addEventListener("abort", () => { clearTimeout(timer); });
             });`,
      filename: SERVER,
    },
    {
      code: "await new Promise((resolve) => { timeoutId = setTimeout(resolve, ms); });",
      filename: SERVER,
    },
    {
      code: `await new Promise((resolve, reject) => {
               timer = setTimeout(() => reject(new Error("timeout")), ms);
             });`,
      filename: SERVER,
    },

    // ---- A reject arm OUTSIDE `Promise.race`/`Promise.any` is a delayed
    // rejection, and `AbortSignal.timeout` is not a substitute for it. ----
    {
      code: `const bomb = new Promise((_, reject) => setTimeout(() => reject(new Error("x")), 1000));`,
      filename: SERVER,
    },
    {
      code: `await Promise.all([work, new Promise((_, reject) => setTimeout(reject, 1000))]);`,
      filename: SERVER,
    },
    // Inside a race, but the timer handle is captured and cleared — no leak.
    {
      code: `await Promise.race([
               work,
               new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("x")), ms); }),
             ]);`,
      filename: SERVER,
    },

    // ---- Shape mismatches. ----
    // Not `Promise`.
    {
      code: "await new Deferred((resolve) => setTimeout(resolve, ms));",
      filename: SERVER,
    },
    // No delay argument at all — not a timed wait.
    {
      code: "await new Promise((resolve) => setTimeout(resolve));",
      filename: SERVER,
    },
    // The callback is not the executor's own resolve.
    {
      code: "await new Promise((resolve) => setTimeout(otherCallback, ms));",
      filename: SERVER,
    },
    // Destructured executor parameter — no identifier to match against.
    {
      code: "await new Promise(({ resolve }) => setTimeout(resolve, ms));",
      filename: SERVER,
    },
    // Not `setTimeout`.
    {
      code: "await new Promise((resolve) => setInterval(resolve, ms));",
      filename: SERVER,
    },
    // A non-global receiver may be a scheduler abstraction, not the timer.
    {
      code: "await new Promise((resolve) => scheduler.setTimeout(resolve, ms));",
      filename: SERVER,
    },

    // ---- File-kind guards. ----
    // Test files belong to `@sarj/no-sleep-in-test-body`, which is enabled in
    // the shipped strict config; double-reporting them helps nobody.
    {
      code: "await new Promise((resolve) => setTimeout(resolve, 50));",
      filename: "/repo/src/lib/queue.test.ts",
    },
    {
      code: "await new Promise((resolve) => setTimeout(resolve, 50));",
      filename: "/repo/tests/queue.ts",
    },
    // One-off tooling dies with the terminal.
    {
      code: "await new Promise((resolve) => setTimeout(resolve, 50));",
      filename: "/repo/scripts/backfill.ts",
    },
    {
      code: "await new Promise((resolve) => setTimeout(resolve, 50));",
      filename: "/repo/audit.mjs",
    },
    // Generated code is overwritten on the next codegen run. In the private
    // corpus the SAME vendored SSE client supplied the only hit in three
    // separate repos, which is why this guard is here rather than assumed.
    {
      code: "await new Promise((resolve) => setTimeout(resolve, 50));",
      filename: "/repo/src/api/generated/core/serverSentEvents.gen.ts",
    },
    {
      code: `/* @generated - do not edit */
             await new Promise((resolve) => setTimeout(resolve, 50));`,
      filename: "/repo/src/api/client.ts",
    },

    // ---- Client modules: the default, and the most important guard. A
    // browser bundle cannot import `node:timers/promises` and the web platform
    // ships no equivalent, so the fix advice is impossible to follow. ----
    {
      code: "await new Promise((resolve) => setTimeout(resolve, 400));",
      filename: "/repo/src/components/AgentPanel.tsx",
    },
    {
      code: `"use client";
             await new Promise((resolve) => setTimeout(resolve, 400));`,
      filename: SERVER,
    },
    {
      code: `import { useState } from "react";
             await new Promise((resolve) => setTimeout(resolve, 400));`,
      filename: SERVER,
    },
    {
      code: `import { useRouter } from "next/navigation";
             await new Promise((resolve) => setTimeout(resolve, 400));`,
      filename: SERVER,
    },

    // ---- The `allowIn` escape hatch: one sanctioned wrapper module. ----
    {
      code: "export const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));",
      filename: "/repo/src/lib/sleep.ts",
      options: [{ allowIn: ["**/lib/sleep.ts"] }],
    },
  ],

  invalid: [
    // ---- The motivating case, verbatim in shape: block-bodied arrow, `void`
    // type argument, delay forwarded from a parameter. ----
    {
      code: `export const defaultSleep: Sleep = async (milliseconds) => {
               await new Promise<void>((resolve) => { setTimeout(resolve, milliseconds); });
             };`,
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    // Concise arrow, no type argument.
    {
      code: "await new Promise((resolve) => setTimeout(resolve, 500));",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    // Returned rather than awaited, wrapped in a named helper — the single most
    // common spelling in both corpora.
    {
      code: "function sleep(ms: number): Promise<void> { return new Promise((resolve) => setTimeout(resolve, ms)); }",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    // `function (resolve) { ... }` — the spelling core `no-promise-executor-return`
    // does not report even when it is enabled.
    {
      code: "await new Promise(function (resolve) { setTimeout(resolve, 250); });",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    // Abbreviated resolve parameter names are the norm in the corpus.
    {
      code: "await new Promise((r) => setTimeout(r, retryAfterMs));",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    // Zero-argument forwarder — still a bare sleep, no value carried.
    {
      code: "await new Promise((resolve) => setTimeout(() => resolve(), 750));",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    {
      code: "await new Promise((resolve) => setTimeout(() => { resolve(); }, 750));",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    // Explicit global receiver.
    {
      code: "await new Promise((resolve) => globalThis.setTimeout(resolve, 300));",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    // A computed delay is still a delay; only a literal `0` is provably a yield.
    {
      code: "await new Promise((resolve) => setTimeout(resolve, 2 ** attempt * baseMs));",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },

    // ---- Client modules, opted in. ----
    {
      code: "await new Promise((resolve) => setTimeout(resolve, 400));",
      filename: "/repo/src/components/AgentPanel.tsx",
      options: [{ checkClientModules: true }],
      errors: [{ messageId: "handRolledSleep" }],
    },
    {
      code: `"use client";
             await new Promise((resolve) => setTimeout(resolve, 400));`,
      filename: SERVER,
      options: [{ checkClientModules: true }],
      errors: [{ messageId: "handRolledSleep" }],
    },

    // ---- The `Promise.race` timeout arm. Reported only when the timer handle
    // is NOT captured, i.e. when the losing arm really does leak. ----
    {
      code: `await Promise.race([
               work(),
               new Promise<never>((_, reject) => setTimeout(() => reject(new Error("timed out")), 15000)),
             ]);`,
      filename: SERVER,
      errors: [{ messageId: "handRolledTimeoutRace" }],
    },
    {
      code: `return Promise.race([
               operation,
               new Promise<T>((_, reject) => {
                 setTimeout(() => { reject(new CacheError("timeout")); }, timeoutMs);
               }),
             ]);`,
      filename: SERVER,
      errors: [{ messageId: "handRolledTimeoutRace" }],
    },
    // `reject` passed directly.
    {
      code: "await Promise.race([work(), new Promise((_, reject) => setTimeout(reject, 1000))]);",
      filename: SERVER,
      errors: [{ messageId: "handRolledTimeoutRace" }],
    },
    // `Promise.any` discards the losing arm the same way.
    {
      code: "await Promise.any([work(), new Promise((_, reject) => setTimeout(reject, 1000))]);",
      filename: SERVER,
      errors: [{ messageId: "handRolledTimeoutRace" }],
    },
    // The race message applies in client modules too — `AbortSignal.timeout`
    // is on the web platform, so unlike the sleep fix it is always available.
    {
      code: "await Promise.race([work(), new Promise((_, reject) => setTimeout(reject, 1000))]);",
      filename: "/repo/src/components/Panel.tsx",
      errors: [{ messageId: "handRolledTimeoutRace" }],
    },
  ],
});
