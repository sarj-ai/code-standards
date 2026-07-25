import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-sentinel-return-on-catch.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-sentinel-return-on-catch", rule, {
  valid: [
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
    // Real site: safe-parse — \`undefined\` on bad input is the contract.
    {
      code: `
        function safeParse(x) {
          try { return JSON.parse(x); }
          catch { return undefined; }
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
    // FP-1: a structured logger is a FREE FUNCTION taking a meta object, and the
    // caught binding is nested inside it behind a conditional. The error IS
    // logged; \`null\` is a deliberate degraded return.
    {
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
    // FP-1: same shape via the \`logFunctions\` option, for a logger whose name
    // does not itself read as a reporting call.
    {
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
    // FP-1: a project-declared logger RECEIVER name.
    {
      code: `
        function load() {
          try { return read(); }
          catch (e) { obs.warn("load failed", e); return null; }
        }
      `,
      options: [{ loggerNames: ["obs"] }],
    },
    // FP-2: \`new URL\` is consumed by a comparison, so the returned expression is
    // a BinaryExpression — the try still hinges on a throwing parse.
    {
      code: `
        function isHttpsUrl(s: string): boolean {
          try { return new URL(s).protocol === 'https:'; }
          catch { return false; }
        }
      `,
    },
    // FP-2: \`await request.json()\` — the await wrapper plus a body-decoding
    // method that throws on malformed input.
    {
      code: `
        async function readBody(request) {
          try { return await request.json(); }
          catch { return null; }
        }
      `,
    },
    // FP-2: a DECLARED \`: boolean\` predicate. A boolean cannot carry error
    // information, so the sentinel is the entire contract.
    {
      code: `
        function canReach(host: string): boolean {
          try { return probe(host); }
          catch { return false; }
        }
      `,
    },
    // FP-2: same, through \`Promise<boolean>\`.
    {
      code: `
        async function canReach(host: string): Promise<boolean> {
          try { return await probe(host); }
          catch { return false; }
        }
      `,
    },
  ],
  invalid: [
    // Regression: the log-detection widening (walk the whole argument subtree so
    // a structured logger's meta object counts) once matched the caught binding
    // by NAME ALONE, which silenced 8 of 18 true positives. Each of these
    // swallows the error while merely mentioning the name in a non-value
    // position. Keep them pinned.
    {
      code: "function a() { try { return risky(); } catch (error) { logCounter({ error: 1 }); return null; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      code: "function b() { try { return risky(); } catch (error) { captureMetric({ tags: { error: 1 } }); return null; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      code: "function c() { try { return risky(); } catch (err) { reportStatus(response.err); return null; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },
    {
      code: "function d() { try { return risky(); } catch (error) { logAll(items.map((error) => error.id)); return null; } }",
      errors: [{ messageId: "noSentinelReturn" }],
    },

    // return null — bare swallow, function otherwise returns real data.
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
    // FP-1 must not over-suppress: declaring \`emit\` as a logger does not excuse
    // a DIFFERENT call that neither logs nor mentions the caught binding.
    {
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
    // FP-2 must not over-suppress: a body decode preceded by real I/O. The catch
    // swallows the network failure too, so \`.json()\` does not excuse it.
    {
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
    // FP-2 must not over-suppress: a declared \`T | null\` return is exactly the
    // shape this rule exists for — nullable accessors hide failures.
    {
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
