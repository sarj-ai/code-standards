import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-sequential-await.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-sequential-await", rule, {
  valid: [
    // The prescribed pattern — concurrent awaits, no await inside the loop.
    {
      code: "async function f(xs) { await Promise.all(xs.map(async (x) => g(x))); }",
    },
    // The `await` is on the for-of ITERABLE — evaluated once, already concurrent.
    {
      code: "async function f(cbs) { for (const r of await Promise.allSettled(cbs)) { handle(r); } }",
    },
    // A poll/throttle loop yielding via a timer helper is deliberately serial.
    {
      code: "async function f() { while (!done()) { await sleep(10); } }",
    },
    {
      code: "async function f() { while (busy) { await this.delay(); } }",
    },
    // Draining a mutable queue is order-dependent — cannot be parallelized.
    {
      code: "async function f() { while (this.queue.length > 0) { await this.queue.shift(); } }",
    },
    // Ordered iterable (name signals a sequence that must run in order).
    {
      code: "async function f(ctx) { for (const key in ctx.teleports) { ctx.teleports[key] = await unroll(key); } }",
    },
    // `for await...of` is correct async iteration and must NOT be flagged.
    {
      code: "async function f(xs) { for await (const x of xs) { handle(x); } }",
    },
    // `for await...of` whose body also contains a (non-loop) await is still fine.
    {
      code: "async function f(xs) { for await (const x of xs) { await handle(x); } }",
    },
    // Await outside any loop.
    {
      code: "async function f() { const a = await one(); const b = await two(); }",
    },
    // Await inside a nested function declaration within the loop — different scope.
    {
      code: "async function f(xs) { for (const x of xs) { async function inner() { await g(x); } inner(); } }",
    },
    // Await inside a nested function expression within the loop — different scope.
    {
      code: "async function f(xs) { while (xs.length) { const run = async function () { await g(); }; run(); } }",
    },
    // A loop with no await at all.
    {
      code: "function f(xs) { for (const x of xs) { use(x); } }",
    },
    // Await in a function whose body is reached after the loop closes.
    {
      code: "async function f(xs) { for (const x of xs) { use(x); } await done(); }",
    },
    // Promise.all built up over a loop without awaiting inside it.
    {
      code: "async function f(xs) { const ps = []; for (const x of xs) { ps.push(g(x)); } await Promise.all(ps); }",
    },
    // Nested loop owns the await — outer loop has no direct await of its own.
    // (The inner loop is the only thing flagged; see the invalid counterpart.)
    {
      code: "async function f(xs) { for (const x of xs) { if (x) { /* no await here */ ok(x); } } }",
    },
    // Guard (a) — retry loop: the `return`/`catch` short-circuit means serial
    // awaits are intentional; parallelizing would break the retry semantics.
    {
      code: "async function f() { for (let i = 0; i < 3; i++) { try { return await attempt(); } catch (e) {} } }",
    },
    // Guard (b) — accumulator threading: each iteration consumes the previous
    // result (`content = await p(content)`), so the awaits cannot be parallel.
    {
      code: "async function f(postProcessors, content) { for (const p of postProcessors) { content = await p(content); } return content; }",
    },
    // Guard (d) — lifecycle hooks: ordering is the contract.
    {
      code: "async function f(hooks, req) { for (const hook of hooks) { await hook(req); } }",
    },
    // Guard (d) — sorted iterable: name signals a deliberately ordered sequence.
    {
      code: "async function f(modulesSortedByDistance) { for (const m of modulesSortedByDistance) { await m.init(); } }",
    },
    // Guard (a) — short-circuit: an early `return` on a failed guard makes the
    // serial awaits load-bearing.
    {
      code: "async function f(guards) { for (const guard of guards) { const r = await guard(); if (!r) return false; } return true; }",
    },
    // Guard (c) — event-loop / timer yield: a deliberate throttle, not I/O.
    {
      code: "async function f(n) { for (let i = 0; i < n; i++) { await new Promise((r) => setTimeout(r, 0)); } }",
    },
    // FP-4 / guard (e) — cursor pagination. The next request's input is the
    // previous response's output, so there is nothing to parallelize. No
    // break/return, and the cursor is assigned from a PROPERTY of the awaited
    // value, so guards (a) and (b) both miss it.
    {
      code: "async function f(out) { let cursor; do { const page = await list(cursor); out.push(...page.items); cursor = page.nextCursor; } while (cursor); }",
    },
    // FP-4 — the `while` form, with a separate `hasMore` flag.
    {
      code: "async function f(out) { let hasMore = true; let cursor = null; while (hasMore) { const page = await list(cursor); out.push(...page.items); hasMore = page.hasMore; cursor = page.cursor; } }",
    },
    // FP-4 — a paging token recomputed each round trip.
    {
      code: "async function f() { let token = ''; while (token !== null) { const res = await fetchPage(token); token = res.nextPageToken; } }",
    },
  ],
  invalid: [
    // for-of with a direct await.
    {
      code: "async function f(xs) { for (const x of xs) { await g(x); } }",
      errors: [{ messageId: "noSequentialAwait" }],
    },
    // C-style for with a direct await in the body.
    {
      code: "async function f(xs) { for (let i = 0; i < xs.length; i++) { await g(xs[i]); } }",
      errors: [{ messageId: "noSequentialAwait" }],
    },
    // for-in with a direct await.
    {
      code: "async function f(obj) { for (const k in obj) { await g(obj[k]); } }",
      errors: [{ messageId: "noSequentialAwait" }],
    },
    // while with a direct await.
    {
      code: "async function f(q) { while (q.length) { await g(q.pop()); } }",
      errors: [{ messageId: "noSequentialAwait" }],
    },
    // do-while with a direct await.
    {
      code: "async function f(q) { do { await g(q.pop()); } while (q.length); }",
      errors: [{ messageId: "noSequentialAwait" }],
    },
    // Await nested in a block / conditional but still directly in the loop scope.
    {
      code: "async function f(xs) { for (const x of xs) { if (x) { await g(x); } } }",
      errors: [{ messageId: "noSequentialAwait" }],
    },
    // Await in the loop's test/condition counts.
    {
      code: "async function f() { while (await next()) { use(); } }",
      errors: [{ messageId: "noSequentialAwait" }],
    },
    // Reported once per loop even with multiple awaits in one loop body.
    {
      code: "async function f(xs) { for (const x of xs) { await g(x); await h(x); } }",
      errors: [{ messageId: "noSequentialAwait" }],
    },
    // Two sibling loops each report independently.
    {
      code: "async function f(xs, ys) { for (const x of xs) { await g(x); } for (const y of ys) { await h(y); } }",
      errors: [
        { messageId: "noSequentialAwait" },
        { messageId: "noSequentialAwait" },
      ],
    },
    // Nested loops: only the inner loop owns its direct await, so exactly one
    // report — the outer loop has no await of its own.
    {
      code: "async function f(xs, ys) { for (const x of xs) { for (const y of ys) { await g(x, y); } } }",
      errors: [{ messageId: "noSequentialAwait" }],
    },
    // Nested loops where BOTH have a direct await — two reports.
    {
      code: "async function f(xs, ys) { for (const x of xs) { await pre(x); for (const y of ys) { await g(x, y); } } }",
      errors: [
        { messageId: "noSequentialAwait" },
        { messageId: "noSequentialAwait" },
      ],
    },
    // Await is the loop body itself (no block).
    {
      code: "async function f(xs) { for (const x of xs) await g(x); }",
      errors: [{ messageId: "noSequentialAwait" }],
    },
    // Genuinely parallelizable: independent awaits whose results are collected
    // with no cross-iteration dependency or early exit — the shape to keep firing.
    {
      code: "async function f(xs, results) { for (const x of xs) { results.push(await fetchOne(x)); } }",
      errors: [{ messageId: "noSequentialAwait" }],
    },
    // FP-4 must not over-suppress: a hand-rolled counter loop steps its own test
    // variable with `++`, the iteration count is known up front, and the awaits
    // are independent — still the parallelizable shape.
    {
      code: "async function f(xs) { let i = 0; while (i < xs.length) { await g(xs[i]); i++; } }",
      errors: [{ messageId: "noSequentialAwait" }],
    },
    // Gap closure: async `.forEach` callback with an await — the classic
    // await-in-loop footgun (the returned promise is dropped on the floor).
    {
      code: "async function f(xs) { xs.forEach(async (x) => { await g(x); }); }",
      errors: [{ messageId: "noSequentialAwait" }],
    },
    // Gap closure: a discarded async `.map` callback floats its promises too.
    {
      code: "async function f(xs, ys) { for (const x of xs) { ys.map(async (y) => await g(y)); } }",
      errors: [{ messageId: "noSequentialAwait" }],
    },
  ],
});
