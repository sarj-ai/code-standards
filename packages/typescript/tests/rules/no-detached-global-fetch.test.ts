import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  NO_DETACHED_GLOBAL_FETCH_DOCUMENTATION,
} from "../../src/rules/no-detached-global-fetch.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });
const PRODUCTION = "/repo/apps/worker/src/client.ts";

RULE_TESTER.run("no-detached-global-fetch", rule, {
  valid: [
    {
      name: "accepts the documented forwarding wrapper",
      filename: PRODUCTION,
      code: NO_DETACHED_GLOBAL_FETCH_DOCUMENTATION.examples[0].files[0].source,
    },
    { name: "allows a direct ambient call", filename: PRODUCTION, code: "await fetch(url, init);" },
    { name: "allows a direct explicit-global call", filename: PRODUCTION, code: "await globalThis.fetch(url, init);" },
    { name: "allows a computed explicit-global call", filename: PRODUCTION, code: "await globalThis['fetch'](url, init);" },
    { name: "allows a matching bound receiver", filename: PRODUCTION, code: "const request = globalThis.fetch.bind(globalThis);" },
    { name: "allows computed binding to a global receiver", filename: PRODUCTION, code: "const request = globalThis.fetch['bind'](globalThis);" },
    { name: "allows self binding", filename: PRODUCTION, code: "const request = self.fetch.bind(self);" },
    { name: "allows another compatible global receiver", filename: PRODUCTION, code: "const request = globalThis.fetch.bind(self);" },
    { name: "allows an explicitly unbound receiver", filename: PRODUCTION, code: "const request = fetch.bind(undefined);" },
    { name: "allows explicit call receiver", filename: PRODUCTION, code: "const response = fetch.call(globalThis, url, init);" },
    { name: "allows computed explicit call receiver", filename: PRODUCTION, code: "const response = fetch['call'](globalThis, url, init);" },
    { name: "allows explicit apply receiver", filename: PRODUCTION, code: "const response = globalThis.fetch.apply(globalThis, args);" },
    { name: "allows computed explicit apply receiver", filename: PRODUCTION, code: "const response = globalThis.fetch['apply'](globalThis, args);" },
    { name: "allows a bare local alias", filename: PRODUCTION, code: "const request = fetch; await request(url, init);" },
    { name: "allows a bare explicit-global alias", filename: PRODUCTION, code: "const request = globalThis.fetch; await request(url, init);" },
    { name: "allows a returned ambient callback", filename: PRODUCTION, code: "function request() { return fetch; }" },
    { name: "allows an ambient callback argument", filename: PRODUCTION, code: "registerTransport(fetch);" },
    { name: "allows a destructured bare alias", filename: PRODUCTION, code: "const { fetch: request } = globalThis; await request(url);" },
    { name: "allows a receiver-safe wrapper around a fallback alias", filename: PRODUCTION, code: "const request = options.request ?? fetch; class Client { readonly fetch = (input: RequestInfo | URL, init?: RequestInit) => request(input, init); }" },
    { name: "allows the repaired workerd forwarding pattern", filename: PRODUCTION, code: "class Client { readonly #request: typeof fetch; constructor(options: { request?: typeof fetch }) { const request = options.request ?? fetch; this.#request = (input, init) => request(input, init); } }" },
    { name: "allows a truthy ambient fetch guard that stores the custom branch", filename: PRODUCTION, code: "const client = { request: fetch && customFetch };" },
    { name: "allows a typeof reference", filename: PRODUCTION, code: "type Fetch = typeof fetch; let request: typeof globalThis.fetch;" },
    { name: "ignores a parameter", filename: PRODUCTION, code: "function client(fetch: typeof globalThis.fetch) { return fetch; }" },
    { name: "ignores an imported implementation", filename: PRODUCTION, code: "import fetch from 'node-fetch'; const request = fetch;" },
    { name: "ignores a local implementation", filename: PRODUCTION, code: "const fetch = makeRequest(); const request = fetch;" },
    { name: "ignores a shadowed receiver", filename: PRODUCTION, code: "function client(globalThis: Runtime) { return globalThis.fetch; }" },
    { name: "ignores object property names", filename: PRODUCTION, code: "const client = { fetch: request };" },
    { name: "ignores object method names", filename: PRODUCTION, code: "const client = { fetch(input: RequestInfo) { return request(input); } };" },
    { name: "ignores class method names", filename: PRODUCTION, code: "class Client { async fetch(input: RequestInfo) { return request(input); } }" },
    { name: "ignores class field names", filename: PRODUCTION, code: "class Client { fetch = request; }" },
    { name: "ignores interface member names", filename: PRODUCTION, code: "interface Client { fetch(input: RequestInfo): Promise<Response>; readonly fetch: typeof globalThis.fetch; }" },
    { name: "ignores type member names", filename: PRODUCTION, code: "type Client = { fetch(input: RequestInfo): Promise<Response>; readonly fetch: typeof globalThis.fetch };" },
    { name: "ignores tests", filename: "/repo/apps/worker/test/client.test.ts", code: "const request = fetch;" },
    { name: "ignores scripts", filename: "/repo/scripts/probe.ts", code: "const request = fetch;" },
    { name: "ignores generated files", filename: "/repo/src/generated/client.ts", code: "const request = fetch;" },
  ],
  invalid: [
    {
      name: "reports the documented receiver-unsafe field",
      filename: PRODUCTION,
      code: NO_DETACHED_GLOBAL_FETCH_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    { name: "reports direct member storage", filename: PRODUCTION, code: "class Client { constructor() { this.request = fetch; } }", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports logical member storage", filename: PRODUCTION, code: "class Client { constructor() { this.request ??= fetch; } }", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports object property storage", filename: PRODUCTION, code: "const client = { request: globalThis.fetch };", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports object shorthand storage", filename: PRODUCTION, code: "const fetch = globalThis.fetch; const client = { fetch };", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports computed explicit-global storage", filename: PRODUCTION, code: "const client = { request: globalThis['fetch'] };", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports a stable alias flowing into a field", filename: PRODUCTION, code: "const request = fetch; class Client { readonly request = request; }", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports a fallback alias flowing into a field", filename: PRODUCTION, code: "class Client { readonly request: typeof fetch; constructor(options: { request?: typeof fetch }) { const request = options.request ?? fetch; this.request = request; } }", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports ambient fetch on the result branch of and", filename: PRODUCTION, code: "const client = { request: customFetch && fetch };", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports ambient fetch on the fallback branch of or", filename: PRODUCTION, code: "const client = { request: customFetch || fetch };", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports ambient fetch on the fallback branch of nullish coalescing", filename: PRODUCTION, code: "const client = { request: customFetch ?? fetch };", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports a defaulted parameter flowing into a field", filename: PRODUCTION, code: "class Client { readonly request: typeof fetch; constructor(request: typeof fetch = fetch) { this.request = request; } }", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports a parameter-property default", filename: PRODUCTION, code: "class Client { constructor(readonly request: typeof fetch = fetch) {} }", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports a destructured alias flowing into a field", filename: PRODUCTION, code: "const { fetch: request } = globalThis; class Client { readonly request = request; }", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports binding to the wrong receiver", filename: PRODUCTION, code: "const request = globalThis.fetch.bind(client);", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports computed binding to the wrong receiver", filename: PRODUCTION, code: "const request = globalThis.fetch['bind'](client);", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports calling with the wrong receiver", filename: PRODUCTION, code: "const response = fetch.call(client, url);", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports computed apply with the wrong receiver", filename: PRODUCTION, code: "const response = fetch['apply'](client, args);", errors: [{ messageId: "detachedGlobalFetch" }] },
  ],
});
