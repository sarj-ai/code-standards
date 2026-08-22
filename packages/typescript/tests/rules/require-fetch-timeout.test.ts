import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { REQUIRE_FETCH_TIMEOUT_DOCUMENTATION } from "../../src/rules/require-fetch-timeout.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

RULE_TESTER.run("require-fetch-timeout", rule, {
  valid: [
    { name: "accepts the documented bounded fetch", code: REQUIRE_FETCH_TIMEOUT_DOCUMENTATION.examples[0].files[0].source },
    {
      name: "ignores codemod fixtures",
      code: "async function f() { await fetch('https://api.example.com/x'); }",
      filename: "/repo/src/v5/remove-overloads/__testfixtures__/bug-reports.input.tsx",
    },
    {
      name: "accepts AbortSignal.timeout",
      code: "await fetch(url, { signal: AbortSignal.timeout(5000) });",
    },
    {
      name: "accepts an AbortController signal",
      code: "await fetch(url, { method: 'POST', signal: controller.signal });",
    },
    {
      name: "accepts a quoted signal key",
      code: "await fetch(url, { 'signal': controller.signal });",
    },
    {
      name: "assumes a spread init may contain a signal",
      code: "await fetch(url, { ...init });",
    },
    {
      name: "assumes a computed init key may be signal",
      code: "await fetch(url, { [key]: value });",
    },
    {
      name: "assumes an identifier init may contain a signal",
      code: "await fetch(url, init);",
    },
    {
      name: "assumes an aliased const object may acquire a signal",
      code: "const init = { method: 'POST' }; const alias = init; await fetch(url, init);",
    },
    {
      name: "assumes a call result init may contain a signal",
      code: "await fetch(url, buildInit());",
    },
    {
      name: "assumes a conditional init may contain a signal",
      code: "await fetch(url, retry ? retryInit : initialInit);",
    },
    {
      name: "allows forwarding a Request",
      code: "await fetch(request);",
    },
    {
      name: "allows forwarding a cloned Request",
      code: "const proxy = (c) => fetch(c.req.raw.clone());",
    },
    {
      name: "allows forwarding a constructed Request",
      code: "await fetch(new Request(url));",
    },
    {
      name: "allows forwarding an object from a locally shadowed URL constructor",
      code: "function proxy(URL) { return fetch(new URL('/x')); }",
    },
    {
      name: "accepts an inline URL object with a signal",
      code: "await fetch(new URL('/v1/items', base), { signal: AbortSignal.timeout(5000) });",
    },
    {
      name: "ignores a service binding fetch",
      code: "await env.MY_SERVICE.fetch(request);",
    },
    {
      name: "ignores a custom client fetch",
      code: "await client.fetch(url);",
    },
    {
      name: "ignores a fetch parameter",
      code: "async function proxy(fetch: typeof globalThis.fetch) { await fetch('/x'); }",
    },
    {
      name: "ignores an imported fetch",
      code: "import fetch from 'node-fetch'; await fetch('/x');",
    },
    {
      name: "ignores a local fetch variable",
      code: "const fetch = makeClient(); await fetch('/x');",
    },
    {
      name: "ignores a shadowed explicit global receiver",
      code: "function request(globalThis) { return globalThis.fetch('/x'); }",
    },
    {
      name: "ignores test files",
      code: "await fetch('/x');",
      filename: "/repo/src/lib/api.test.ts",
    },
    {
      name: "ignores test directories",
      code: "await fetch('/x');",
      filename: "/repo/src/__tests__/helpers.ts",
    },
    {
      name: "ignores script directories",
      code: "await fetch('/x');",
      filename: "/repo/scripts/backfill.ts",
    },
    {
      name: "ignores mjs tooling",
      code: "await fetch('/x');",
      filename: "/repo/tools/one-off.mjs",
    },
    {
      name: "allows a configured wrapper module",
      code: "await fetch('/x');",
      options: [{ allowIn: ["**/http-client.ts"] }],
      filename: "/repo/src/lib/http-client.ts",
    },
  ],
  invalid: [
    { name: "reports the documented unbounded fetch", code: REQUIRE_FETCH_TIMEOUT_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "missingSignal" }] },
    {
      name: "rejects a production fetch without a signal",
      code: "async function f() { await fetch('https://api.example.com/x'); }",
      filename: "/repo/src/clients/api-client.ts",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects an inline relative URL without an init",
      code: "await fetch('/api/things');",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects an inline absolute URL without an init",
      code: "const res = await fetch('https://api.example.com/v1/things');",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects a template literal URL without an init",
      code: "await fetch(`/api/items/${id}`);",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects an inline URL object without an init",
      code: "await fetch(new URL('/v1/items', base));",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects an object init without a signal",
      code: "await fetch(url, { method: 'POST', body });",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects an empty object init",
      code: "await fetch(url, {});",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects a static const init whose only mutation cannot add a signal",
      code: "const init: RequestInit = { method: 'POST' }; init.body = body; await fetch(url, init);",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects globalThis.fetch without a signal",
      code: "await globalThis.fetch('/api/things');",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects window.fetch without a signal",
      code: "await window.fetch(url, { method: 'POST' });",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects self.fetch without a signal",
      code: "await self.fetch('/api/things');",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "does not exempt a file outside allowIn",
      code: "await fetch('/x');",
      options: [{ allowIn: ["**/http-client.ts"] }],
      filename: "/repo/src/routes/page.ts",
      errors: [{ messageId: "missingSignal" }],
    },
  ],
});
