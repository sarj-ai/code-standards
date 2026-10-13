// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, expect, it } from "vitest";

import rule, {
  REQUIRE_FETCH_TIMEOUT_DOCUMENTATION,
} from "../../src/rules/require-fetch-timeout.js";

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
    {
      name: "accepts shadowed undefined",
      code: "function send(undefined: AbortSignal) { fetch('/x', {signal: undefined}); }",
    },
    {
      name: "accepts a later signal override",
      code: "fetch('/x', {signal: null, ...options});",
    },
    {
      name: "accepts a later explicit signal",
      code: "fetch('/x', {signal: null, signal: controller.signal});",
    },
    {
      name: "ignores an unknown computed override",
      code: "fetch('/x', {signal: null, [key]: value});",
    },
    {
      name: "ignores a signal getter",
      code: "fetch('/x', {get signal() { return null; }});",
    },
    {
      name: "abstains when an accessor can attach a signal during conversion",
      code: "const init = ({get headers() { this.signal = controller.signal; return {}; }} as RequestInit); fetch('/x', init);",
    },
    {
      name: "abstains when an accessor can replace a later null signal",
      code: "const init = {get headers() { this.signal = controller.signal; return {}; }, signal: null}; fetch('/x', init);",
    },
    {
      name: "abstains when an accessor can replace an earlier null signal",
      code: "const init = {signal: null, get headers() { this.signal = controller.signal; return {}; }}; fetch('/x', init);",
    },
    {
      name: "does not infer a forwarded Request reset through an accessor",
      code: "fetch(new Request('/x'), {get headers() { this.signal = controller.signal; return {}; }, signal: null});",
    },
    {
      name: "does not infer a later null reset through an inherited accessor",
      code: "fetch('/x', {__proto__: {get headers() { this.signal = controller.signal; return {}; }}, signal: null});",
    },
    {
      name: "does not infer an earlier null reset through an inherited accessor",
      code: "fetch('/x', {signal: null, __proto__: {get headers() { this.signal = controller.signal; return {}; }}});",
    },
    {
      name: "abstains on an unproved prototype that can supply an accessor",
      code: "fetch('/x', {signal: null, __proto__: optionsPrototype});",
    },
    {
      name: "preserves an undefined Request signal override",
      code: "fetch(new Request('/x'), {signal: undefined});",
    },
    {
      name: "preserves a Request signal after unknown spread",
      code: "fetch(new Request('/x'), {signal: null, ...options});",
    },
    {
      name: "preserves a wrapped valid signal",
      code: "fetch('/x', ({signal: controller.signal} satisfies RequestInit));",
    },
    {
      name: "preserves shadowed computed globals",
      code: "function send(globalThis) { globalThis['fetch']('/x'); }",
    },
    {
      name: "preserves a literal prototype signal",
      code: "fetch('/x', {__proto__: {signal: controller.signal}});",
    },
    {
      name: "abstains when a prototype write can supply an inherited signal",
      code: "const init = {} as RequestInit & { __proto__: RequestInit }; init.__proto__ = {signal: controller.signal}; fetch('/x', init);",
    },
    {
      name: "ignores a local init acquiring a signal",
      code: "const init = {signal: null}; init.signal = controller.signal; fetch('/x', init);",
    },
    {
      name: "ignores void with side effects",
      code: "fetch('/x', {signal: void configure()});",
    },

    {
      name: "preserves a Request signal with an inline init",
      code: "fetch(new Request('/items', {signal: AbortSignal.timeout(5000)}), {method: 'POST'});",
    },
    {
      name: "preserves a forwarded Request signal with a local init",
      code: "const request = new Request('/items', {signal: controller.signal}); const init = {method: 'POST'}; fetch(request, init);",
    },
    {
      name: "preserves an asserted forwarded Request signal",
      code: "fetch((new Request('/x', {signal: controller.signal}) as Request), {});",
    },
    {
      name: "preserves a satisfies wrapped forwarded Request signal",
      code: "fetch((new Request('/x', {signal: controller.signal}) satisfies Request), {});",
    },
    {
      name: "preserves an asserted const Request initializer and argument",
      code: "const request = new Request('/x', {signal: controller.signal}) as Request; fetch((request as Request), {});",
    },
    {
      name: "preserves a forwarded Request through an erased constructor wrapper",
      code: "fetch(new (Request as typeof Request)('/x', {signal: controller.signal}), {});",
    },
    {
      name: "accepts the documented bounded fetch",
      code: REQUIRE_FETCH_TIMEOUT_DOCUMENTATION.examples[0].files[0].source,
    },
    {
      name: "ignores codemod fixtures",
      code: "async function f() { await fetch('https://api.example.com/x'); }",
      filename:
        "/repo/src/v5/remove-overloads/__testfixtures__/bug-reports.input.tsx",
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
    {
      name: "checks computed global fetch",
      code: "globalThis['fetch']('/x');",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "checks an erased init assertion",
      code: "fetch('/x', ({} as RequestInit));",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "checks an erased null assertion",
      code: "fetch('/x', {signal: (null as AbortSignal | null)});",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "checks an immutable wrapped init",
      code: "const init = ({signal: null} satisfies RequestInit); fetch('/x', init);",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "checks an explicit absent init",
      code: "fetch('/x', undefined);",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "checks an explicit null init",
      code: "fetch('/x', null);",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects resetting a Request signal",
      code: "fetch(new Request('/x'), {signal: null});",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects resetting a wrapped forwarded Request signal",
      code: "fetch((new Request('/x', {signal: controller.signal}) as Request), {signal: null});",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "does not infer inherited cancellation from a shadowed Request",
      code: "function send(Request: Factory) { fetch(new (Request as Factory)('/x'), {}); }",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects resetting an aliased Request signal",
      code: "const request = new Request('/x', {signal: controller.signal}); const init = {signal: null}; fetch(request, init);",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects an own null overriding a prototype signal",
      code: "fetch('/x', {signal: null, __proto__: {signal: controller.signal}});",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects null signal",
      code: "fetch('/x', {'signal': null});",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects undefined signal",
      code: "fetch('/x', {'signal': undefined});",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects void zero signal",
      code: "fetch('/x', {'signal': void 0});",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects null after a spread",
      code: "fetch('/x', {...options, signal: null});",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects a final null override",
      code: "fetch('/x', {signal: controller.signal, signal: null});",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects a computed literal null signal",
      code: "fetch('/x', {['signal']: null});",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      name: "rejects an immutable local null signal",
      code: "const init = {signal: null}; fetch('/x', init);",
      errors: [{ messageId: "missingSignal" }],
    },

    {
      name: "reports the documented unbounded fetch",
      code: REQUIRE_FETCH_TIMEOUT_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "missingSignal" }],
    },
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

it("distinguishes Request signal reset from signal inheritance", () => {
  const controller = new AbortController();
  const initial = new Request("https://example.com", {
    signal: controller.signal,
  });
  const reset = new Request(initial, { signal: null });
  const inherited = new Request(initial, { signal: undefined });
  controller.abort();
  expect(initial.signal.aborted).toBe(true);
  expect(reset.signal.aborted).toBe(false);
  expect(inherited.signal.aborted).toBe(true);
});

it("inherits cancellation from a RequestInit prototype assigned before use", () => {
  const controller = new AbortController();
  const init: RequestInit = {};
  expect(Reflect.set(init, "__proto__", { signal: controller.signal })).toBe(
    true,
  );
  const request = new Request("https://example.com", init);
  controller.abort();
  expect(request.signal.aborted).toBe(true);
});

it("reads RequestInit accessor effects before the signal regardless of declaration order", () => {
  const controller = new AbortController();
  const options: readonly RequestInit[] = [
    {
      get headers() {
        this.signal = controller.signal;
        return {};
      },
      signal: null,
    },
    {
      signal: null,
      get headers() {
        this.signal = controller.signal;
        return {};
      },
    },
  ];
  const requests = options.map(
    (init) => new Request("https://example.com", init),
  );
  controller.abort();
  for (const request of requests) expect(request.signal.aborted).toBe(true);
});

it("reads inherited RequestInit accessor effects before an own null signal", () => {
  const controller = new AbortController();
  const init: RequestInit = { signal: null };
  expect(
    Reflect.setPrototypeOf(init, {
      get headers() {
        Reflect.set(this, "signal", controller.signal);
        return {};
      },
    }),
  ).toBe(true);
  const request = new Request("https://example.com", init);
  controller.abort();
  expect(request.signal.aborted).toBe(true);
});
