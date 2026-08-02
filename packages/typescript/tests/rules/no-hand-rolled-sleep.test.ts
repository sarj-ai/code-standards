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

const SERVER = "/repo/src/lib/queue.ts";

ruleTester.run("no-hand-rolled-sleep", rule, {
  valid: [
    {
      name: "accepts the cancellable Node timer",
      code: `import { setTimeout as sleep } from "node:timers/promises";
             await sleep(500, undefined, { signal });`,
      filename: SERVER,
    },
    {
      name: "accepts AbortSignal.timeout",
      code: `const signal = AbortSignal.timeout(5000);
             await work({ signal });`,
      filename: SERVER,
    },
    {
      name: "accepts a concise macrotask yield",
      code: "await new Promise((resolve) => setTimeout(resolve, 0));",
      filename: SERVER,
    },
    {
      name: "accepts a block-bodied macrotask yield",
      code: "await new Promise((resolve) => { setTimeout(resolve, 0); });",
      filename: SERVER,
    },
    {
      name: "accepts a delayed fallback value",
      code: "await new Promise((resolve) => setTimeout(() => resolve(fallback), 4000));",
      filename: SERVER,
    },
    {
      name: "accepts a block-bodied delayed fallback value",
      code: "await new Promise((resolve) => setTimeout(() => { resolve(fallback); }, 4000));",
      filename: SERVER,
    },
    {
      name: "accepts a timer cleared on abort",
      code: `await new Promise((resolve) => {
               const timer = setTimeout(resolve, ms);
               signal.addEventListener("abort", () => { clearTimeout(timer); });
             });`,
      filename: SERVER,
    },
    {
      name: "accepts an executor that captures its timer",
      code: "await new Promise((resolve) => { timeoutId = setTimeout(resolve, ms); });",
      filename: SERVER,
    },
    {
      name: "accepts a rejection executor that captures its timer",
      code: `await new Promise((resolve, reject) => {
               timer = setTimeout(() => reject(new Error("timeout")), ms);
             });`,
      filename: SERVER,
    },
    {
      name: "accepts a delayed rejection outside a race",
      code: `const bomb = new Promise((_, reject) => setTimeout(() => reject(new Error("x")), 1000));`,
      filename: SERVER,
    },
    {
      name: "accepts a delayed rejection in Promise.all",
      code: `await Promise.all([work, new Promise((_, reject) => setTimeout(reject, 1000))]);`,
      filename: SERVER,
    },
    {
      name: "accepts a race arm that captures its timer",
      code: `await Promise.race([
               work,
               new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("x")), ms); }),
             ]);`,
      filename: SERVER,
    },
    {
      name: "ignores delayed rejection nested below a race arm",
      code: `await Promise.race([
               work,
               wrap(new Promise((_, reject) => setTimeout(reject, ms))),
             ]);`,
      filename: SERVER,
    },
    {
      name: "ignores non-Promise constructors",
      code: "await new Deferred((resolve) => setTimeout(resolve, ms));",
      filename: SERVER,
    },
    {
      name: "ignores a timer without a delay",
      code: "await new Promise((resolve) => setTimeout(resolve));",
      filename: SERVER,
    },
    {
      name: "ignores a timer with an unrelated callback",
      code: "await new Promise((resolve) => setTimeout(otherCallback, ms));",
      filename: SERVER,
    },
    {
      name: "ignores a destructured executor parameter",
      code: "await new Promise(({ resolve }) => setTimeout(resolve, ms));",
      filename: SERVER,
    },
    {
      name: "ignores setInterval",
      code: "await new Promise((resolve) => setInterval(resolve, ms));",
      filename: SERVER,
    },
    {
      name: "ignores scheduler abstractions",
      code: "await new Promise((resolve) => scheduler.setTimeout(resolve, ms));",
      filename: SERVER,
    },
    {
      name: "leaves colocated tests to no-sleep-in-test-body",
      code: "await new Promise((resolve) => setTimeout(resolve, 50));",
      filename: "/repo/src/lib/queue.test.ts",
    },
    {
      name: "leaves test directories to no-sleep-in-test-body",
      code: "await new Promise((resolve) => setTimeout(resolve, 50));",
      filename: "/repo/tests/queue.ts",
    },
    {
      name: "ignores scripts directories",
      code: "await new Promise((resolve) => setTimeout(resolve, 50));",
      filename: "/repo/scripts/backfill.ts",
    },
    {
      name: "ignores root scripts",
      code: "await new Promise((resolve) => setTimeout(resolve, 50));",
      filename: "/repo/audit.mjs",
    },
    {
      name: "ignores generated file paths",
      code: "await new Promise((resolve) => setTimeout(resolve, 50));",
      filename: "/repo/src/api/generated/core/serverSentEvents.gen.ts",
    },
    {
      name: "ignores generated file markers",
      code: `/* @generated - do not edit */
             await new Promise((resolve) => setTimeout(resolve, 50));`,
      filename: "/repo/src/api/client.ts",
    },
    {
      name: "ignores JSX modules by default",
      code: "await new Promise((resolve) => setTimeout(resolve, 400));",
      filename: "/repo/src/components/AgentPanel.tsx",
    },
    {
      name: "ignores use-client modules by default",
      code: `"use client";
             await new Promise((resolve) => setTimeout(resolve, 400));`,
      filename: SERVER,
    },
    {
      name: "ignores React modules by default",
      code: `import { useState } from "react";
             await new Promise((resolve) => setTimeout(resolve, 400));`,
      filename: SERVER,
    },
    {
      name: "ignores Next client modules by default",
      code: `import { useRouter } from "next/navigation";
             await new Promise((resolve) => setTimeout(resolve, 400));`,
      filename: SERVER,
    },
    {
      name: "honors an allowIn glob",
      code: "export const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));",
      filename: "/repo/src/lib/sleep.ts",
      options: [{ allowIn: ["**/lib/sleep.ts"] }],
    },
    {
      name: "leaves polling loops to no-await-in-loop",
      code: "while (!done) { await sleep(50); }",
      filename: SERVER,
    },
  ],

  invalid: [
    {
      name: "reports a typed block-bodied sleep",
      code: `export const defaultSleep: Sleep = async (milliseconds) => {
               await new Promise<void>((resolve) => { setTimeout(resolve, milliseconds); });
             };`,
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    {
      name: "reports a concise sleep",
      code: "await new Promise((resolve) => setTimeout(resolve, 500));",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    {
      name: "reports a returned sleep helper",
      code: "function sleep(ms: number): Promise<void> { return new Promise((resolve) => setTimeout(resolve, ms)); }",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    {
      name: "reports a function-expression executor",
      code: "await new Promise(function (resolve) { setTimeout(resolve, 250); });",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    {
      name: "reports an abbreviated resolve parameter",
      code: "await new Promise((r) => setTimeout(r, retryAfterMs));",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    {
      name: "reports a concise zero-argument forwarder",
      code: "await new Promise((resolve) => setTimeout(() => resolve(), 750));",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    {
      name: "reports a block-bodied zero-argument forwarder",
      code: "await new Promise((resolve) => setTimeout(() => { resolve(); }, 750));",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    {
      name: "reports an explicit global timer",
      code: "await new Promise((resolve) => globalThis.setTimeout(resolve, 300));",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    {
      name: "reports a computed delay",
      code: "await new Promise((resolve) => setTimeout(resolve, 2 ** attempt * baseMs));",
      filename: SERVER,
      errors: [{ messageId: "handRolledSleep" }],
    },
    {
      name: "reports JSX modules when opted in",
      code: "await new Promise((resolve) => setTimeout(resolve, 400));",
      filename: "/repo/src/components/AgentPanel.tsx",
      options: [{ checkClientModules: true }],
      errors: [{ messageId: "handRolledSleep" }],
    },
    {
      name: "reports use-client modules when opted in",
      code: `"use client";
             await new Promise((resolve) => setTimeout(resolve, 400));`,
      filename: SERVER,
      options: [{ checkClientModules: true }],
      errors: [{ messageId: "handRolledSleep" }],
    },
    {
      name: "reports a concise Promise.race timeout arm",
      code: `await Promise.race([
               work(),
               new Promise<never>((_, reject) => setTimeout(() => reject(new Error("timed out")), 15000)),
             ]);`,
      filename: SERVER,
      errors: [{ messageId: "handRolledTimeoutRace" }],
    },
    {
      name: "reports a block-bodied Promise.race timeout arm",
      code: `return Promise.race([
               operation,
               new Promise<T>((_, reject) => {
                 setTimeout(() => { reject(new CacheError("timeout")); }, timeoutMs);
               }),
             ]);`,
      filename: SERVER,
      errors: [{ messageId: "handRolledTimeoutRace" }],
    },
    {
      name: "reports reject passed directly in Promise.race",
      code: "await Promise.race([work(), new Promise((_, reject) => setTimeout(reject, 1000))]);",
      filename: SERVER,
      errors: [{ messageId: "handRolledTimeoutRace" }],
    },
    {
      name: "reports reject passed directly in Promise.any",
      code: "await Promise.any([work(), new Promise((_, reject) => setTimeout(reject, 1000))]);",
      filename: SERVER,
      errors: [{ messageId: "handRolledTimeoutRace" }],
    },
    {
      name: "reports race timeout arms in client modules",
      code: "await Promise.race([work(), new Promise((_, reject) => setTimeout(reject, 1000))]);",
      filename: "/repo/src/components/Panel.tsx",
      errors: [{ messageId: "handRolledTimeoutRace" }],
    },
  ],
});
