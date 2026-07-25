import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/require-fetch-timeout.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("require-fetch-timeout", rule, {
  valid: [
    // signal present.
    {
      code: "await fetch(url, { signal: AbortSignal.timeout(5000) });",
    },
    {
      code: "await fetch(url, { method: 'POST', signal: controller.signal });",
    },
    // Quoted signal key still counts.
    {
      code: "await fetch(url, { 'signal': controller.signal });",
    },
    // Spread may carry a signal — assumed safe.
    {
      code: "await fetch(url, { ...init });",
    },
    // Computed key could be 'signal' at runtime — assumed safe.
    {
      code: "await fetch(url, { [key]: value });",
    },
    // Non-literal init (identifier / call / conditional) — conservative skip.
    {
      code: "await fetch(url, init);",
    },
    {
      code: "await fetch(url, buildInit());",
    },
    // Proxy passthrough: a lone non-string argument is a Request being
    // forwarded (Workers idiom) — attaching a fresh signal is impossible/wrong.
    {
      code: "await fetch(request);",
    },
    {
      code: "const proxy = (c) => fetch(c.req.raw.clone());",
    },
    {
      code: "await fetch(new Request(url));",
    },
    // Member-expression fetches are out of scope (Cloudflare service bindings,
    // custom clients).
    {
      code: "await env.MY_SERVICE.fetch(request);",
    },
    {
      code: "await client.fetch(url);",
    },
    // A local binding shadowing `fetch` is not the global — injected fetches
    // are the caller's responsibility.
    {
      code: "async function proxy(fetch: typeof globalThis.fetch) { await fetch('/x'); }",
    },
    {
      code: "import fetch from 'node-fetch'; await fetch('/x');",
    },
    {
      code: "const fetch = makeClient(); await fetch('/x');",
    },
    // Test files and one-off tooling paths are exempt.
    {
      code: "await fetch('/x');",
      filename: "/repo/src/lib/api.test.ts",
    },
    {
      code: "await fetch('/x');",
      filename: "/repo/src/__tests__/helpers.ts",
    },
    {
      code: "await fetch('/x');",
      filename: "/repo/scripts/backfill.ts",
    },
    {
      code: "await fetch('/x');",
      filename: "/repo/tools/one-off.mjs",
    },
    // allowIn glob exempts wrapper modules (matched against the ABSOLUTE path).
    {
      code: "await fetch('/x');",
      options: [{ allowIn: ["**/http-client.ts"] }],
      filename: "/repo/src/lib/http-client.ts",
    },
  ],
  invalid: [
    // Inline-URL calls with no init argument.
    {
      code: "await fetch('/api/things');",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      code: "const res = await fetch('https://api.example.com/v1/things');",
      errors: [{ messageId: "missingSignal" }],
    },
    // Template-literal URL is still an inline URL, not a passthrough.
    {
      code: "await fetch(`/api/items/${id}`);",
      errors: [{ messageId: "missingSignal" }],
    },
    // Object-literal init provably lacking a signal (any first argument).
    {
      code: "await fetch(url, { method: 'POST', body });",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      code: "await fetch(url, {});",
      errors: [{ messageId: "missingSignal" }],
    },
    // Explicit-global spellings are in scope.
    {
      code: "await globalThis.fetch('/api/things');",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      code: "await window.fetch(url, { method: 'POST' });",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      code: "await self.fetch('/api/things');",
      errors: [{ messageId: "missingSignal" }],
    },
    // allowIn only exempts matching files.
    {
      code: "await fetch('/x');",
      options: [{ allowIn: ["**/http-client.ts"] }],
      filename: "/repo/src/routes/page.ts",
      errors: [{ messageId: "missingSignal" }],
    },
  ],
});
