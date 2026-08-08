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

// Most fixtures below carry a statement AFTER the `try`. That is deliberate: it
// keeps them out of the terminal-error-boundary exemption so they go on pinning
// what they were written to pin (which statements count toward the limit).
// Fixtures that exercise the exemption itself are grouped at the end of each
// list and say so.
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
          finish();
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
          finish();
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
          finish();
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
          finish();
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
          finish();
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
          finish();
        }
      `,
    },
    // Async callbacks return rejected promises; the enclosing synchronous map
    // call does not throw those callback failures into this catch.
    {
      code: `
        function f(rows) {
          try {
            const a = rows.map(async (row) => await one(row));
            const b = rows.map(async (row) => await two(row));
            const c = rows.map(async (row) => await three(row));
            const d = rows.map(async (row) => await four(row));
          } catch (e) { handle(e); }
          finish();
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
          finish();
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
          finish();
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
          finish();
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
          finish();
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
          finish();
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
          finish();
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
          finish();
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
          finish();
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
          return fallback();
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
          return fallback();
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
          finish();
        }
      `,
    },

    // --- Terminal error-propagating boundary (the 83%-of-findings exemption) ---

    // HTTP route handler: the try is the whole body and the catch turns any
    // failure into one error response. Nothing is mis-attributed.
    {
      code: `
        export async function POST(req) {
          try {
            const rawBody = await req.text();
            await verifySignature({ req, rawBody });
            const res = await fetch(RATES_URL);
            const { data } = await res.json();
            await redis.hset("fxRates:usd", data);
            return NextResponse.json(data);
          } catch (error) {
            await log({ message: \`Error updating FX rates: \${error.message}\` });
            return handleAndReturnErrorResponse(error);
          }
        }
      `,
    },
    // RPC handler: the handler is a single bare call that converts the error to
    // the transport's error type.
    {
      code: `
        async function getMaintenance(req, ctx) {
          try {
            const rpcCtx = await getRpcContext(ctx);
            const svcCtx = await toServiceCtx(rpcCtx);
            const full = await loadMaintenance({ ctx: svcCtx, id: req.id });
            const ids = await loadComponentIds(full);
            return { maintenance: toProto(full, ids) };
          } catch (err) {
            toConnectError(err);
          }
        }
      `,
    },
    // Result-type boundary: logs the error and returns a typed error variant.
    // Not a success-shaped swallow, so the exemption applies.
    {
      code: `
        async function createContact(input) {
          try {
            const parsed = await schema.parseAsync(input);
            const org = await getOrganization(parsed.orgId);
            const env = await getEnvironment(org.id);
            const contact = await db.contact.create({ data: parsed });
            return ok(contact);
          } catch (error) {
            logger.error({ error }, "createContact failed");
            return err({ type: "internal_server_error" });
          }
        }
      `,
    },
    // The exemption reaches through an \`if\` that is itself terminal — nothing
    // in the function runs after the try either way.
    {
      code: `
        async function handler(req, res) {
          if (req.method === "POST") {
            try {
              const body = await parse(req);
              const user = await authenticate(req);
              const saved = await save(user, body);
              const enriched = await enrich(saved);
              return res.json(enriched);
            } catch (e) {
              errorHandler(e, res);
            }
          }
        }
      `,
    },
    {
      name: "terminal boundaries accept destructured catch bindings",
      code: `
        async function f() {
          try {
            await one();
            await two();
            await three();
            await four();
          } catch ({ message }) {
            return failure(message);
          }
        }
      `,
    },
    // The purity model, negative side. These must STAY silent after `JSON.parse`
    // and the Map/Set verbs stopped counting as pure by name.
    {
      code: `
        function h(xs) {
          try {
            const a = xs.map(String);
            const b = xs.filter(Boolean);
            const c = xs.join(",");
            const d = Object.keys(xs);
            use(a, b, c, d);
          } catch (e) { handle(e); }
          finish();
        }
      `,
    },
    // `JSON.stringify` stays pure: it is overwhelmingly called on a value the
    // same function just built. A recall choice, not an oversight.
    {
      code: `
        function j(a, b, c, d) {
          try {
            const w = JSON.stringify(a);
            const x = JSON.stringify(b);
            const y = JSON.stringify(c);
            const z = JSON.stringify(d);
            use(w, x, y, z);
          } catch (e) { handle(e); }
          finish();
        }
      `,
    },
    // Fire-and-forget `cache.set(...)` is still exempt structurally, so dropping
    // `set` from the name-only pure list did not resurrect the class that
    // `isBareCallStatement` exists to suppress.
    {
      code: `
        function m(cache) {
          try {
            cache.set("a", 1);
            cache.set("b", 2);
            cache.set("c", 3);
            cache.set("d", 4);
          } catch (e) { handle(e); }
          finish();
        }
      `,
    },
  ],
  invalid: [
    {
      name: "explicit throws in synchronous collection callbacks propagate",
      code: `
        function f(rows) {
          try {
            const a = rows.map((row) => { if (!row.a) throw new Error('a'); return row; });
            const b = rows.map((row) => { if (!row.b) throw new Error('b'); return row; });
            const c = rows.map((row) => { if (!row.c) throw new Error('c'); return row; });
            const d = rows.map((row) => { if (!row.d) throw new Error('d'); return row; });
          } catch (error) { handle(error); }
          finish();
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "awaits nested in four branches still exceed the limit",
      code: `
        async function f(flags) {
          try {
            if (flags.a) await one();
            if (flags.b) await two();
            if (flags.c) await three();
            if (flags.d) await four();
          } catch (error) { handle(error); }
          finish();
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "terminal handlers may not return null",
      code: `
        async function f() {
          try {
            await one();
            await two();
            await three();
            await four();
          } catch (error) {
            report(error);
            return null;
          }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "terminal handlers may not return undefined",
      code: `
        async function f() {
          try {
            await one();
            await two();
            await three();
            await four();
          } catch (error) {
            report(error);
            return undefined;
          }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "terminal handlers may not return false",
      code: `
        async function f() {
          try {
            await one();
            await two();
            await three();
            await four();
          } catch (error) {
            report(error);
            return false;
          }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "an error-shaped property key does not reference the caught error",
      code: `
        async function f() {
          try {
            await one();
            await two();
            await three();
            await four();
          } catch (error) {
            return failure({ error: "hidden" });
          }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "assignment-ending handlers are recovery rather than propagation",
      code: `
        async function f() {
          try {
            await one();
            await two();
            await three();
            await four();
          } catch (error) {
            state.failure = error;
          }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "a try at the end of a switch case is not a terminal boundary",
      code: `
        async function f(kind) {
          switch (kind) {
            case "sync":
              try {
                await one();
                await two();
                await three();
                await four();
              } catch (error) {
                report(error);
              }
          }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // `JSON.parse` is the canonical throwing call and the canonical reason to
    // write try/catch, and it was on the "pure, non-throwing" list.
    {
      code: `
        function f(a, b, c, d) {
          try {
            const w = JSON.parse(a);
            const x = JSON.parse(b);
            const y = JSON.parse(c);
            const z = JSON.parse(d);
            use(w, x, y, z);
          } catch (e) { handle(e); }
          finish();
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // `PURE_METHODS` matched by method NAME only, so every I/O client that
    // borrows the Map/Set vocabulary read as pure data plumbing.
    {
      code: `
        function g(client, redis, repo, api) {
          try {
            const a = client.get("/1");
            const b = redis.set("k", 1);
            const c = repo.find({});
            const d = api.delete("id");
            use(a, b, c, d);
          } catch (e) { handle(e); }
          finish();
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
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
          finish();
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
          finish();
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
          finish();
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
          finish();
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
          finish();
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
          finish();
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
          finish();
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
          finish();
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
          finish();
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },

    // --- Upper bounds on the terminal-error-boundary exemption ---
    // Each of these is a true positive from the corpus read. They must keep
    // firing or the exemption has widened into a no-op.

    // Clause (b): the handler INSPECTS the error and falls back to a different
    // transport. Its last statement is a branch, not a hand-off, so which
    // statement threw changes what the handler does.
    {
      code: `
        async function sendWelcomeMessage({ channelId, token, webhookUrl }) {
          try {
            const client = await createWebClient({ token });
            await ensureBotInChannel({ client, channelId });
            const app = await createApp({ token });
            await app.chat.postMessage({ channel: channelId, text: "hi" });
          } catch (err) {
            const isChannelNotFound =
              typeof err === "object" && err !== null && err.code === "channel_not_found";
            if (isChannelNotFound) {
              await postToWebhook(webhookUrl);
            }
          }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // Clause (a): the try is NOT terminal — the catch resets state and the
    // function goes on to retry with another strategy, so a failure in an early
    // statement silently changes what the retry sees.
    {
      code: `
        async function fetchTransactions(accountId) {
          let all = [];
          try {
            const first = await get(accountId, { strategy: "longest" });
            const merged = await merge(all, first);
            const recent = await get(accountId, { strategy: "recent" });
            const sorted = await sort(merged, recent);
            all = sorted;
          } catch (e) {
            logFailure(e);
          }
          const fallback = await get(accountId, { strategy: "default" });
          return all.concat(fallback);
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // Clause (d): a long body whose handler logs and returns an EMPTY ARRAY. A
    // configuration bug in any one of these statements becomes "no contacts
    // found" at the call site — the success-shaped swallow the rule exists for.
    {
      code: `
        async function getContacts(emails) {
          try {
            const conn = await this.conn;
            const options = await this.getAppOptions();
            const fieldNames = await this.getObjectFieldNames(options.record);
            const soql = await buildSoql(emails, fieldNames);
            const results = await conn.query(soql);
            return results.records.map((r) => ({ id: r.Id }));
          } catch (error) {
            log.error("Error in getContacts", safeStringify(error));
            return [];
          }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // Clause (d), object shape: an empty object is just as success-shaped.
    {
      code: `
        async function loadSettings(orgId) {
          try {
            const org = await getOrg(orgId);
            const prefs = await getPrefs(org.id);
            const flags = await getFlags(org.id);
            const theme = await getTheme(org.id);
            return { ...prefs, ...flags, ...theme };
          } catch (error) {
            logger.warn(error);
            return {};
          }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // Clause (c): the handler never touches the error. A uniform 500 that
    // discards the cause is not error propagation, it is a swallow.
    {
      code: `
        export async function GET(req) {
          try {
            const session = await getSession(req);
            const org = await getOrg(session.orgId);
            const rows = await db.query(org.id);
            const shaped = await shape(rows);
            return NextResponse.json(shaped);
          } catch {
            return NextResponse.json({ error: "failed" }, { status: 500 });
          }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    // Clause (a): last in the LOOP body is not terminal — the next iteration
    // runs after the handler.
    {
      code: `
        async function syncAll(ids) {
          for (const id of ids) {
            try {
              const item = await load(id);
              const norm = await normalize(item);
              const saved = await save(norm);
              const indexed = await index(saved);
            } catch (e) {
              report(e);
            }
          }
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
  ],
});
