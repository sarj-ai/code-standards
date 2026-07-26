import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-fat-try-blocks.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-fat-try-blocks", rule, {
  valid: [
    // Generated request clients are template output, not hand-authored error
    // handling worth reshaping.
    {
      code: `
        async function request() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch (e) { return undefined; }
        }
      `,
      filename: "/repo/src/openapi-gen/requests/core/request.ts",
    },
    // Exactly three throwing (result-using) statements — at the limit.
    {
      code: `
        function f() {
          try {
            const a = one();
            const b = two();
            const c = three();
          } catch (e) { handle(e); }
        }
      `,
    },
    // Exactly three awaits — at the limit.
    {
      code: `
        async function f() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
          } catch (e) { handle(e); }
        }
      `,
    },
    // Four statements but only three throw — pure member access is free.
    {
      code: `
        function f() {
          try {
            const a = one();
            const b = a.field;
            const c = two();
            const d = three();
          } catch (e) { handle(e); }
        }
      `,
    },
    // Dominant real-world pattern: ONE awaited action, then trailing
    // fire-and-forget side effects (setters/toast/router/callback). Not fat.
    {
      code: `
        async function f() {
          try {
            await assignTrunk(orgId, trunkId);
            setOpen(false);
            setSelectedOrgId("");
            toast("Success");
            router.refresh();
            onSuccess?.();
          } catch (e) { setError(e); }
        }
      `,
    },
    // Bare fire-and-forget call statements do not count (no await, value used).
    {
      code: `
        function f() {
          try {
            log("a");
            emit("b");
            notify("c");
            track("d");
          } catch (e) { handle(e); }
        }
      `,
    },
    // Pure array / object plumbing does not count, even when assigned.
    {
      code: `
        function f() {
          try {
            const ids = rows.map((r) => r.id);
            const names = rows.filter(Boolean).map((r) => r.name);
            const keys = Object.keys(obj);
            const joined = ids.join(",");
            const has = set.has(x);
          } catch (e) { handle(e); }
        }
      `,
    },
    // `finally` present — exempt regardless of body size.
    {
      code: `
        async function f() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } finally { cleanup(); }
        }
      `,
    },
    // Handler re-throws on its last statement — uniform error wrapping, exempt.
    {
      code: `
        async function f() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch (e) {
            log(e);
            throw new Error("wrapped", { cause: e });
          }
        }
      `,
    },
    // Handler re-throws (bare) — exempt.
    {
      code: `
        async function f() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch (e) { throw e; }
        }
      `,
    },
    // Throwing calls only in the catch, not the try body.
    {
      code: `
        function f() {
          try {
            const a = one();
          } catch (e) {
            const b = recover(e);
            const c = retry(b);
            const d = report(c);
            const g = finalize(d);
          }
        }
      `,
    },
    // Calls only inside nested function bodies do not count toward the limit.
    {
      code: `
        function f() {
          try {
            const cb1 = () => alpha();
            const cb2 = () => beta();
            const cb3 = () => gamma();
            const cb4 = () => delta();
          } catch (e) { handle(e); }
        }
      `,
    },
    // Compound statements collapse to one each (an if/for/switch counts once).
    {
      code: `
        function f() {
          try {
            if (cond) { const a = a1(); const b = b1(); const c = c1(); }
            for (const x of xs) { const d = d1(x); }
            switch (k) { case 1: { const e = e1(); break; } }
          } catch (e) { handle(e); }
        }
      `,
    },
    // Long body of pure computation + a SINGLE awaited action. Only the await
    // throws; reduce/map/filter/join and template literals are free.
    {
      code: `
        async function f() {
          try {
            const sum = items.reduce((a, b) => a + b, 0);
            const names = items.map((i) => i.name);
            const filtered = names.filter(Boolean);
            const joined = filtered.join(", ");
            const label = \`Total: \${sum}\`;
            const result = await save(label, joined);
          } catch (e) { handle(e); }
        }
      `,
    },
    // ONE risky call then a fat tail of non-throwing cleanup: setState with a
    // functional update, toast, console.log, analytics, optional callback.
    {
      code: `
        async function f() {
          try {
            const res = await createOrder(payload);
            setOrders((prev) => [...prev, res]);
            toast.success("Created");
            console.log("done", res.id);
            analytics.track("order_created");
            onDone?.();
          } catch (e) { toast.error(String(e)); }
        }
      `,
    },
    // finally with MANY cleanup statements but the try holds one await — exempt.
    {
      code: `
        async function f() {
          try {
            const conn = await pool.acquire();
          } finally {
            release();
            reset();
            clearTimers();
            flushMetrics();
            logDone();
          }
        }
      `,
    },
    // Building an accumulator in a loop then one await — loop collapses to one.
    {
      code: `
        async function f() {
          try {
            const acc = [];
            for (const row of rows) {
              acc.push(row.id);
            }
            const saved = await persist(acc);
          } catch (e) { handle(e); }
        }
      `,
    },
    // Destructuring + pure Object/Array plumbing + one await.
    {
      code: `
        async function f() {
          try {
            const entries = Object.entries(config);
            const keys = Object.keys(config);
            const merged = { ...defaults, ...config };
            const list = Array.from(keys);
            const data = await load(merged);
          } catch (e) { handle(e); }
        }
      `,
    },
    // SSE / streaming API handler: ONE real await plus non-throwing web-platform
    // constructors (TextEncoder / ReadableStream / Blob / Response). Only the
    // await throws; the constructors are stream/response plumbing, not I/O.
    {
      code: `
        async function GET() {
          try {
            await ensureDatabase();
            const encoder = new TextEncoder();
            const blob = new Blob(["ping"]);
            const stream = new ReadableStream({ start() {} });
            const res = new Response(stream);
            return res;
          } catch (e) { handle(e); }
        }
      `,
    },
    // FP-3: the bare-call exemption must survive a guard. Six statements, but
    // only the three awaits can throw — the three \`if\` guards each contain a
    // fire-and-forget log plus a return.
    {
      code: `
        async function f(path) {
          try {
            const res = await fetch(path);
            if (!res.ok) { logEvent('http_error', { path }); return null; }
            const body = await res.json();
            if (!body) { logEvent('empty_body', { path }); return null; }
            const parsed = await parseBody(body);
            if (!parsed) { logEvent('unparsed', { path }); return null; }
            return parsed;
          } catch (e) { handle(e); }
        }
      `,
    },
    // FP-3: the same exemption through an \`else\` branch.
    {
      code: `
        function f(x) {
          try {
            if (x) { track('a'); } else { track('b'); }
            if (x) { track('c'); } else { track('d'); }
            if (x) { track('e'); } else { track('f'); }
            if (x) { track('g'); } else { track('h'); }
          } catch (e) { handle(e); }
        }
      `,
    },
  ],
  invalid: [
    // FP-3 must not over-suppress: a call whose RESULT is branched on still
    // counts, even though the guard body is bare fire-and-forget.
    {
      code: `
        function f(x) {
          try {
            if (!validate(x)) { track('a'); return null; }
            if (!check(x)) { track('b'); return null; }
            if (!verify(x)) { track('c'); return null; }
            if (!confirm(x)) { track('d'); return null; }
          } catch (e) { handle(e); }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // FP-3 must not over-suppress: a result-using call inside a guard body counts.
    {
      code: `
        function f(x) {
          try {
            if (x) { const a = one(); }
            if (x) { const b = two(); }
            if (x) { const c = three(); }
            if (x) { const d = four(); }
          } catch (e) { handle(e); }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // Four result-using calls — boundary just over the limit.
    {
      code: `
        function f() {
          try {
            const a = one();
            const b = two();
            const c = three();
            const d = four();
          } catch (e) { handle(e); }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // Four awaits — multiple independent I/O ops under one swallowing catch.
    {
      code: `
        async function f() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch (e) { handle(e); }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // Mixed awaits and result-using sync calls push over the limit.
    {
      code: `
        async function f() {
          try {
            const cfg = parse(raw);
            const res = await fetch(cfg.url);
            const data = await res.json();
            const out = transform(data);
          } catch (e) { handle(e); }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // `new` (non-pure constructor) whose value is used counts.
    {
      code: `
        function f() {
          try {
            const a = new Widget(x);
            const b = new Gadget(y);
            const c = new Gizmo(z);
            const d = new Doohickey(w);
          } catch (e) { handle(e); }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // Handler does NOT re-throw (final statement swallows) — fires.
    {
      code: `
        async function f() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch (e) {
            log(e);
            return null;
          }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // A conditional throw that is not the last statement does not exempt.
    {
      code: `
        async function f() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch (e) {
            if (fatal(e)) throw e;
            log(e);
          }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // Nested-function calls are ignored, but the real throwing statements
    // around them still push the count over the limit.
    {
      code: `
        function f() {
          try {
            const cb = () => nestedCall();
            const a = one();
            const b = two();
            const c = three();
            const d = four();
          } catch (e) { handle(e); }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // Non-throwing web constructors are free, but four real awaits alongside
    // them are still four throwing ops — must fire (no under-firing).
    {
      code: `
        async function f() {
          try {
            const encoder = new TextEncoder();
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
            const res = new Response(null);
          } catch (e) { handle(e); }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
  ],
});
