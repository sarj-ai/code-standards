// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_FAT_TRY_BLOCKS_DOCUMENTATION } from "../../src/rules/no-fat-try-blocks.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});






RULE_TESTER.run("no-fat-try-blocks", rule, {
  valid: [
    {
      name: "allows a higher calibrated threshold",
      options: [{ max: 5 }],
      code: `try { const a = one(); const b = two(); const c = three(); const d = four(); } catch (error) { handle(error); }`,
    },


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

    {
      code: NO_FAT_TRY_BLOCKS_DOCUMENTATION.examples[0].files[0].source,
    },

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


    {
      name: "allows simple catch-finally orchestration",
      code: `
        async function render() {
          try {
            const source = await loadSource();
            const parsed = await parseSource(source);
            const image = await renderImage(parsed);
            const saved = await saveImage(image);
          } catch {
            markFailed();
          } finally {
            markIdle();
          }
          finish();
        }
      `,
    },

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
      name: "keeps simple catch without finally",
      code: `
        async function render() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch { markFailed(); }
          finish();
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "keeps catch with a binding",
      code: `
        async function render() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch (error) { markFailed(error); }
          finally { markIdle(); }
          finish();
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "keeps catch with multiple statements",
      code: `
        async function render() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch { logFailure(); markFailed(); }
          finally { markIdle(); }
          finish();
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "keeps finally with multiple statements",
      code: `
        async function render() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch { markFailed(); }
          finally { markIdle(); reportDuration(); }
          finish();
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "keeps inline callback in catch call",
      code: `
        async function render() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch { recover(() => markFailed()); }
          finally { markIdle(); }
          finish();
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "keeps assignment in catch call",
      code: `
        async function render() {
          let failed = false;
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch { markFailed(failed = true); }
          finally { markIdle(); }
          finish();
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "keeps update in finally call",
      code: `
        async function render() {
          let attempts = 0;
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch { markFailed(); }
          finally { recordAttempts(attempts++); }
          finish();
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "keeps awaited catch call",
      code: `
        async function render() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch { await recover(); }
          finally { markIdle(); }
          finish();
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
    {
      name: "does not let a finalizer exempt a catch boundary",
      code: `
        async function f() {
          try {
            const a = await one();
            const b = await two();
            const c = await three();
            const d = await four();
          } catch (e) {
            handle(e);
          } finally {
            cleanup();
          }
          finish();
        }
      `,
      errors: [{ messageId: "fatTryBlock" }],
    },
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

    {
      code: NO_FAT_TRY_BLOCKS_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "fatTryBlock" }],
    },

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
