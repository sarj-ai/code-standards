import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_SENTINEL_RETURN_ON_CATCH_DOCUMENTATION } from "../../src/rules/no-sentinel-return-on-catch.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

RULE_TESTER.run("no-sentinel-return-on-catch", rule, {
  valid: [
    { name: "accepts the documented reported fallback", code: NO_SENTINEL_RETURN_ON_CATCH_DOCUMENTATION.examples[0].files[0].source },
    {
      name: "ignores generated request clients",
      code: "async function request() { try { return await run(); } catch { return undefined; } }",
      filename: "/repo/src/openapi-gen/requests/core/request.ts",
    },
    {
      name: "allows an unannotated predicate named with an Exists suffix",
      code: "async function directoryExists(p) { try { const s = await stat(p); return s.isDirectory(); } catch { return false; } }",
    },
    {
      name: "allows an unannotated predicate named with an is prefix",
      code: "function isClientReference(x) { try { return x.$$typeof === SYM; } catch { return false; } }",
    },
    {
      name: "allows an unannotated predicate assigned to a variable",
      code: "const hasDependency = ({ name }) => { try { return Boolean(require.resolve(name)); } catch { return false; } };",
    },
    {
      name: "allows the same sentinel on a normal ternary path",
      code: "function verify(value, valid) { try { return valid ? value : false; } catch { return false; } }",
    },
    {
      name: "allows null on both a normal ternary path and the catch path",
      code: "function readVersion(content) { try { const p = parse(content); return typeof p.version === 'string' ? p.version : null; } catch { return null; } }",
    },
    {
      name: "allows the same sentinel on a nullish-coalescing path",
      code: "function lookup(id) { try { return cache.get(id) ?? null; } catch { return null; } }",
    },
    {
      name: "allows the same sentinel on an or-fallback path",
      code: "function enabled(config) { try { return config.enabled || false; } catch { return false; } }",
    },
    {
      name: "allows undefined when optional chaining models ordinary absence",
      code: "function readTitle(config) { try { return config.current?.title; } catch { return undefined; } }",
    },
    {
      name: "leaves promise catch handlers to no-silent-promise-catch",
      code: "async function load() { return request().catch(() => []); }",
    },
    // Rethrow — the canonical correct handling.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) { throw e; }
        }
      `,
    },
    // Throws a wrapped error.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) { throw new Error("wrapped", { cause: e }); }
        }
      `,
    },
    // Throw appears before a later return — still rethrows, not swallowed.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) {
            if (isFatal(e)) throw e;
            return null;
          }
        }
      `,
    },
    // Returns a meaningful computed value (function call).
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) { return fallback(e); }
        }
      `,
    },
    // Returns a meaningful variable.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) {
            const result = recover(e);
            return result;
          }
        }
      `,
    },
    // Returns a member expression — meaningful.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) { return defaults.value; }
        }
      `,
    },
    // Returns a non-empty array literal — meaningful.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) { return [fallbackItem]; }
        }
      `,
    },
    // Returns a non-empty object literal — meaningful.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) { return { ok: false, error: e }; }
        }
      `,
    },
    // \`return 0\` is often legitimate — not flagged.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) { return 0; }
        }
      `,
    },
    // \`return ""\` is often legitimate — not flagged.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) { return ""; }
        }
      `,
    },
    // Bare \`return;\` — out of scope for this rule.
    {
      code: `
        function f() {
          try { run(); }
          catch (e) { return; }
        }
      `,
    },
    // Sentinel return is NOT the final statement — conservative, not flagged.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) {
            if (cond) return null;
            return recover(e);
          }
        }
      `,
    },
    // Empty catch body — nothing returned, not flagged.
    {
      code: `
        function f() {
          try { run(); }
          catch (e) {}
        }
      `,
    },
    // Logs then rethrows — final statement is a throw, not a sentinel return.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) {
            log(e);
            throw e;
          }
        }
      `,
    },
    // Real site: error IS logged (console.error), \`[]\` is a degraded return.
    {
      code: `
        function fetchRows() {
          try { return query(); }
          catch (e) {
            console.error("query failed", e);
            return [];
          }
        }
      `,
    },
    // Real site: error reported to a central handler, \`undefined\` is the
    // declared \`T | undefined\` contract.
    {
      code: `
        function lookup(id) {
          try { return store.get(id); }
          catch (err) {
            onUnexpectedError(err);
            return undefined;
          }
        }
      `,
    },
    // Real site: logger receiver call before the sentinel return.
    {
      code: `
        function load() {
          try { return read(); }
          catch (e) {
            logger.warn("load failed", e);
            return null;
          }
        }
      `,
    },
    {
      name: "allows JSON.parse as a safe-parse contract",
      code: `
        function safeParse(x) {
          try { return JSON.parse(x); }
          catch { return undefined; }
        }
      `,
    },
    {
      name: "allows a safe parse after earlier work in the try body",
      code: `
        function readConfig(text) {
          try {
            let parsed;
            parsed = JSON.parse(text);
            return parsed;
          } catch { return null; }
        }
      `,
    },
    {
      name: "allows pure array validation after JSON parsing",
      code: `
        function parseMessages(text) {
          try {
            const parsed = JSON.parse(text);
            return Array.isArray(parsed) ? parsed : [];
          } catch { return []; }
        }
      `,
    },
    {
      name: "allows optional browser-storage reads around JSON parsing",
      code: `
        function readRecent() {
          try {
            const parsed = JSON.parse(window.localStorage.getItem('recent') ?? '[]');
            return Array.isArray(parsed) ? parsed : [];
          } catch { return []; }
        }
      `,
    },
    {
      name: "allows a deliberate Error throw used only to capture and inspect its stack",
      code: `
        function inferMarker() {
          try { throw Error(); }
          catch (error) {
            const stack = error.stack;
            inspect(stack);
            return null;
          }
        }
      `,
    },
    // Real site: \`new RegExp\` safe-construct — \`null\` on invalid pattern.
    {
      code: `
        function compile(pattern) {
          try { return new RegExp(pattern); }
          catch { return null; }
        }
      `,
    },
    // Real site: boolean predicate — a normal path also returns a boolean.
    {
      code: `
        function hasFeature(name) {
          if (!name) return false;
          try { return registry.check(name); }
          catch { return false; }
        }
      `,
    },
    {
      name: "allows reporting a caught error nested in structured metadata",
      code: `
        async function scan(repo) {
          try { return await github.listOpenPullRequests(repo); }
          catch (err) {
            logEvent('pr_scan.list_failed', { repo, error: err instanceof Error ? err.message : String(err) });
            return null;
          }
        }
      `,
    },
    {
      name: "allows a configured free logging function",
      code: `
        async function scan(repo) {
          try { return await github.listOpenPullRequests(repo); }
          catch (err) {
            emit('pr_scan.list_failed', { repo, cause: String(err) });
            return null;
          }
        }
      `,
      options: [{ logFunctions: ["emit"] }],
    },
    {
      name: "allows a configured logger receiver",
      code: `
        function load() {
          try { return read(); }
          catch (e) { obs.warn("load failed", e); return null; }
        }
      `,
      options: [{ loggerNames: ["obs"] }],
    },
    {
      name: "allows an explicit failure log when a bare catch has no binding",
      code: `
        function load() {
          try { return read(); }
          catch { logger.warn("load failed"); return null; }
        }
      `,
    },
    {
      name: "allows a safe constructor nested in a returned comparison",
      code: `
        function isHttpsUrl(s: string): boolean {
          try { return new URL(s).protocol === 'https:'; }
          catch { return false; }
        }
      `,
    },
    {
      name: "allows a sole awaited body decoder",
      code: `
        async function readBody(request) {
          try { return await request.json(); }
          catch { return null; }
        }
      `,
    },
    {
      name: "allows a declared boolean predicate",
      code: `
        function canReach(host: string): boolean {
          try { return probe(host); }
          catch { return false; }
        }
      `,
    },
    {
      name: "allows a cast sentinel in a declared boolean predicate",
      code: "function isReady(): boolean { try { return probe(); } catch { return false as boolean; } }",
    },
    {
      name: "does not treat a non-null assertion as a sentinel",
      code: "function load() { try { return read(); } catch { return cached!; } }",
    },
    {
      name: "allows a declared asynchronous boolean predicate",
      code: `
        async function canReach(host: string): Promise<boolean> {
          try { return await probe(host); }
          catch { return false; }
        }
      `,
    },
  ],
  invalid: [
    { name: "reports the documented silent fallback", code: NO_SENTINEL_RETURN_ON_CATCH_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "noSentinelReturn" }] },
    {
      name: "does not exempt a deliberate Error throw when the caught value is ignored",
      code: "function f() { try { throw Error(); } catch (error) { return null; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "does not exempt an operational throw merely because the caught value is read",
      code: "function f() { try { throw run(); } catch (error) { inspect(error); return null; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "reports a nullable sentinel behind an as assertion",
      code: "function load() { try { return read(); } catch { return null as User | null; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "reports an empty object behind an angle-bracket assertion",
      code: "function load() { try { return read(); } catch { return <Config>{}; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "reports an empty array behind satisfies",
      code: "function load() { try { return read(); } catch { return [] satisfies Row[]; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "reports a nullable return from a predicate-named function",
      code: "function isReady(p) { try { return load(p); } catch { return null; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "reports an empty collection from a non-predicate",
      code: "async function loadRows(p) { try { return await query(p); } catch { return []; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "does not mistake an object key for a caught-error read",
      code: "function a() { try { return risky(); } catch (error) { logCounter({ error: 1 }); return null; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "does not mistake a nested object key for a caught-error read",
      code: "function b() { try { return risky(); } catch (error) { captureMetric({ tags: { error: 1 } }); return null; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "does not mistake another object's property for the caught error",
      code: "function c() { try { return risky(); } catch (err) { reportStatus(response.err); return null; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "does not hide an earlier operational failure behind a later parse",
      code: "function readConfig(path) { try { const text = read(path); return JSON.parse(text); } catch { return null; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "does not treat an arbitrary getItem call as browser-storage parsing",
      code: "function readConfig(db) { try { return JSON.parse(db.getItem('config')); } catch { return null; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "does not treat an ordinary empty result as permission to hide failure",
      code: "async function readAll() { if (!configured()) return []; try { return await storage.getAll(); } catch { return []; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "does not count a shadowing callback parameter as the caught error",
      code: "function d() { try { return risky(); } catch (error) { logAll(items.map((error) => error.id)); return null; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },

    // return null — bare swallow, function otherwise returns real data.
    {
      name: "does not treat a parse inside a nested callback as safe parsing",
      code: `
        function load(items) {
          try { return items.map((item) => JSON.parse(item)); }
          catch { return null; }
        }
      `,
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "reports a declared nullable accessor contract",
      code: `
        async function fetchThing(id: string): Promise<Thing | undefined> {
          try { return await load(id); }
          catch { return undefined; }
        }
      `,
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) { return null; }
        }
      `,
      errors: [{ messageId: "noSentinelReturn" }],
    },
    // return undefined — no logging, no safe-parse contract.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) { return undefined; }
        }
      `,
      errors: [{ messageId: "noSentinelReturn" }],
    },
    // return false — no normal-path boolean, so not a predicate contract.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) { return false; }
        }
      `,
      errors: [{ messageId: "noSentinelReturn" }],
    },
    // return [] — empty array, the classic idempotency-breaking swallow.
    {
      code: `
        function f() {
          try { return fetchRows(); }
          catch (e) { return []; }
        }
      `,
      errors: [{ messageId: "noSentinelReturn" }],
    },
    // return {} — empty object.
    {
      code: `
        function f() {
          try { return fetchMap(); }
          catch (e) { return {}; }
        }
      `,
      errors: [{ messageId: "noSentinelReturn" }],
    },
    // Non-logging work then a sentinel return still swallows the error.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) {
            cleanup();
            return [];
          }
        }
      `,
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "requires the configured logging function to be called",
      code: `
        async function scan(repo) {
          try { return await list(repo); }
          catch (err) {
            track('pr_scan.started', { repo });
            return null;
          }
        }
      `,
      options: [{ logFunctions: ["emit"] }],
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "requires a bound caught error to reach the logging call",
      code: `
        function load() {
          try { return read(); }
          catch (error) {
            logger.warn("load failed");
            return null;
          }
        }
      `,
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "reports a body decoder when the try also performs I/O",
      code: `
        async function load(url) {
          try {
            const res = await fetch(url);
            return await res.json();
          } catch { return null; }
        }
      `,
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      name: "reports a declared nullable return contract",
      code: `
        async function fetchThing(id: string): Promise<Thing | null> {
          try { return await load(id); }
          catch { return null; }
        }
      `,
      errors: [{ messageId: "noSentinelReturn" }],
    },
    // A throw inside a NESTED function does not count as rethrow for this catch,
    // and register() neither logs nor reports the error.
    {
      code: `
        function f() {
          try { return run(); }
          catch (e) {
            const onError = () => { throw e; };
            register(onError);
            return null;
          }
        }
      `,
      errors: [{ messageId: "noSentinelReturn" }],
    },
  ],
});
