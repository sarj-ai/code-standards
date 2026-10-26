// vitest: shared-module-graph
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
    { name: "does not inherit fetch identity through a second var initializer", filename: PRODUCTION, code: "var request = fetch; var request = customFetch; const client = { request };" },
    { name: "includes later alias writes in the stable-reference proof", filename: PRODUCTION, code: "let request = fetch; const client = { request }; request = customFetch;" },
    {
      name: "accepts the documented forwarding wrapper",
      filename: PRODUCTION,
      code: NO_DETACHED_GLOBAL_FETCH_DOCUMENTATION.examples[0].files[0].source,
    },
    {
      name: "allows a direct ambient call",
      filename: PRODUCTION,
      code: "await fetch(url, init);",
    },
    {
      name: "allows a direct explicit-global call",
      filename: PRODUCTION,
      code: "await globalThis.fetch(url, init);",
    },
    {
      name: "allows a computed explicit-global call",
      filename: PRODUCTION,
      code: "await globalThis['fetch'](url, init);",
    },
    {
      name: "allows a matching bound receiver",
      filename: PRODUCTION,
      code: "const request = globalThis.fetch.bind(globalThis);",
    },
    {
      name: "allows computed binding to a global receiver",
      filename: PRODUCTION,
      code: "const request = globalThis.fetch['bind'](globalThis);",
    },
    {
      name: "allows self binding",
      filename: PRODUCTION,
      code: "const request = self.fetch.bind(self);",
    },
    {
      name: "allows another compatible global receiver",
      filename: PRODUCTION,
      code: "const request = globalThis.fetch.bind(self);",
    },
    {
      name: "allows an explicitly unbound receiver",
      filename: PRODUCTION,
      code: "const request = fetch.bind(undefined);",
    },
    {
      name: "allows explicit call receiver",
      filename: PRODUCTION,
      code: "const response = fetch.call(globalThis, url, init);",
    },
    {
      name: "allows computed explicit call receiver",
      filename: PRODUCTION,
      code: "const response = fetch['call'](globalThis, url, init);",
    },
    {
      name: "allows explicit apply receiver",
      filename: PRODUCTION,
      code: "const response = globalThis.fetch.apply(globalThis, args);",
    },
    {
      name: "allows computed explicit apply receiver",
      filename: PRODUCTION,
      code: "const response = globalThis.fetch['apply'](globalThis, args);",
    },
    {
      name: "allows a bare local alias",
      filename: PRODUCTION,
      code: "const request = fetch; await request(url, init);",
    },
    {
      name: "allows a bare explicit-global alias",
      filename: PRODUCTION,
      code: "const request = globalThis.fetch; await request(url, init);",
    },
    {
      name: "allows a returned ambient callback",
      filename: PRODUCTION,
      code: "function request() { return fetch; }",
    },
    {
      name: "allows an ambient callback argument",
      filename: PRODUCTION,
      code: "registerTransport(fetch);",
    },
    {
      name: "allows a destructured bare alias",
      filename: PRODUCTION,
      code: "const { fetch: request } = globalThis; await request(url);",
    },
    {
      name: "allows a receiver-safe wrapper around a fallback alias",
      filename: PRODUCTION,
      code: "const request = options.request ?? fetch; class Client { readonly fetch = (input: RequestInfo | URL, init?: RequestInit) => request(input, init); }",
    },
    {
      name: "allows the repaired workerd forwarding pattern",
      filename: PRODUCTION,
      code: "class Client { readonly #request: typeof fetch; constructor(options: { request?: typeof fetch }) { const request = options.request ?? fetch; this.#request = (input, init) => request(input, init); } }",
    },
    {
      name: "allows a truthy ambient fetch guard that stores the custom branch",
      filename: PRODUCTION,
      code: "const client = { request: fetch && customFetch };",
    },
    {
      name: "allows a typeof reference",
      filename: PRODUCTION,
      code: "type Fetch = typeof fetch; let request: typeof globalThis.fetch;",
    },
    {
      name: "ignores a parameter",
      filename: PRODUCTION,
      code: "function client(fetch: typeof globalThis.fetch) { return fetch; }",
    },
    {
      name: "ignores an imported implementation",
      filename: PRODUCTION,
      code: "import fetch from 'node-fetch'; const request = fetch;",
    },
    {
      name: "ignores a local implementation",
      filename: PRODUCTION,
      code: "const fetch = makeRequest(); const request = fetch;",
    },
    {
      name: "ignores a shadowed receiver",
      filename: PRODUCTION,
      code: "function client(globalThis: Runtime) { return globalThis.fetch; }",
    },
    {
      name: "ignores object property names",
      filename: PRODUCTION,
      code: "const client = { fetch: request };",
    },
    {
      name: "ignores object method names",
      filename: PRODUCTION,
      code: "const client = { fetch(input: RequestInfo) { return request(input); } };",
    },
    {
      name: "ignores class method names",
      filename: PRODUCTION,
      code: "class Client { async fetch(input: RequestInfo) { return request(input); } }",
    },
    {
      name: "ignores class field names",
      filename: PRODUCTION,
      code: "class Client { fetch = request; }",
    },
    {
      name: "ignores interface member names",
      filename: PRODUCTION,
      code: "interface Client { fetch(input: RequestInfo): Promise<Response>; readonly fetch: typeof globalThis.fetch; }",
    },
    {
      name: "ignores type member names",
      filename: PRODUCTION,
      code: "type Client = { fetch(input: RequestInfo): Promise<Response>; readonly fetch: typeof globalThis.fetch };",
    },
    {
      name: "ignores tests",
      filename: "/repo/apps/worker/test/client.test.ts",
      code: "const request = fetch;",
    },
    {
      name: "ignores scripts",
      filename: "/repo/scripts/probe.ts",
      code: "const request = fetch;",
    },
    {
      name: "ignores generated files",
      filename: "/repo/src/generated/client.ts",
      code: "const request = fetch;",
    },
  ],
  invalid: [
    { name: "retains a fetch alias through a bare var redeclaration", filename: PRODUCTION, code: "var request = fetch; var request; const client = { request };", errors: [{ messageId: "detachedGlobalFetch" }] },
    {
      name: "refuses erased local object declarations",
      code: "export function load() { declare const client = { request: fetch }; return client.request('data:text/plain,hello'); }",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
      filename: "/repo/src/client.ts",
    },
    {
      name: "repairs the sole private literal request receiver",
      code: "export function load() { const client = { request: fetch }; return client.request('data:text/plain,hello'); }",
      filename: "/repo/src/client.ts",
      output:
        "export function load() { const client = { request: fetch.bind(undefined) }; return client.request('data:text/plain,hello'); }",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "preserves shorthand storage keys",
      code: "export function load() { const client = { fetch }; return client.fetch('data:text/plain,hello'); }",
      filename: "/repo/src/client.ts",
      output:
        "export function load() { const client = { fetch: fetch.bind(undefined) }; return client.fetch('data:text/plain,hello'); }",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "preserves CRLF and static computed reads",
      code: "export function load() {\r\n  const client = { request: fetch };\r\n  return client['request']('data:text/plain,hello');\r\n}",
      filename: "/repo/src/client.ts",
      output:
        "export function load() {\r\n  const client = { request: fetch.bind(undefined) };\r\n  return client['request']('data:text/plain,hello');\r\n}",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains imported authority",
      code: "import \"setup\"; export function load() { const client = { request: fetch }; return client.request('data:text/plain,hello'); }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains source comments",
      code: "/* receiver contract */ export function load() { const client = { request: fetch }; return client.request('data:text/plain,hello'); }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains callable identity escapes",
      code: "export function load() { const client = { request: fetch }; return client; }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains other local effects",
      code: "export function load() { const client = { request: fetch }; observe(client); return client.request('data:text/plain,hello'); }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains unknown request inputs",
      code: "export function load(input: string) { const client = { request: fetch }; return client.request(input); }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains request option contracts",
      code: "export function load() { const client = { request: fetch }; return client.request('data:text/plain,hello', {}); }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains networking policy choices",
      code: "export function load() { const client = { request: fetch }; return client.request('https://example.test/'); }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains shadowed undefined",
      code: "export function load() { const undefined = { request: fetch }; return undefined.request('data:text/plain,hello'); }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains explicit return contracts",
      code: "export function load(): Promise<Response> { const client = { request: fetch }; return client.request('data:text/plain,hello'); }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains annotated object contracts",
      code: "export function load() { const client: {request: typeof fetch} = { request: fetch }; return client.request('data:text/plain,hello'); }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains prototype initializer semantics",
      code: "export function load() { const client = { __proto__: fetch }; return client.__proto__('data:text/plain,hello'); }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains computed storage semantics",
      code: "export function load() { const client = { ['request']: fetch }; return client.request('data:text/plain,hello'); }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains mutable object bindings",
      code: "export function load() { let client = { request: fetch }; return client.request('data:text/plain,hello'); }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains additional stored fields",
      code: "export function load() { const client = { request: fetch, value: 1 }; return client.request('data:text/plain,hello'); }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "retains explicit global receiver authority",
      code: "export function load() { const client = { request: globalThis.fetch }; return client.request('data:text/plain,hello'); }",
      filename: "/repo/src/client.ts",
      output: null,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports the documented receiver-unsafe field",
      filename: PRODUCTION,
      code: NO_DETACHED_GLOBAL_FETCH_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports direct member storage",
      filename: PRODUCTION,
      code: "class Client { constructor() { this.request = fetch; } }",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports logical member storage",
      filename: PRODUCTION,
      code: "class Client { constructor() { this.request ??= fetch; } }",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports object property storage",
      filename: PRODUCTION,
      code: "const client = { request: globalThis.fetch };",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports object shorthand storage",
      filename: PRODUCTION,
      code: "const fetch = globalThis.fetch; const client = { fetch };",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports computed explicit-global storage",
      filename: PRODUCTION,
      code: "const client = { request: globalThis['fetch'] };",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports a stable alias flowing into a field",
      filename: PRODUCTION,
      code: "const request = fetch; class Client { readonly request = request; }",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports a fallback alias flowing into a field",
      filename: PRODUCTION,
      code: "class Client { readonly request: typeof fetch; constructor(options: { request?: typeof fetch }) { const request = options.request ?? fetch; this.request = request; } }",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports ambient fetch on the result branch of and",
      filename: PRODUCTION,
      code: "const client = { request: customFetch && fetch };",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports ambient fetch on the fallback branch of or",
      filename: PRODUCTION,
      code: "const client = { request: customFetch || fetch };",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports ambient fetch on the fallback branch of nullish coalescing",
      filename: PRODUCTION,
      code: "const client = { request: customFetch ?? fetch };",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports a defaulted parameter flowing into a field",
      filename: PRODUCTION,
      code: "class Client { readonly request: typeof fetch; constructor(request: typeof fetch = fetch) { this.request = request; } }",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports a parameter-property default",
      filename: PRODUCTION,
      code: "class Client { constructor(readonly request: typeof fetch = fetch) {} }",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports a destructured alias flowing into a field",
      filename: PRODUCTION,
      code: "const { fetch: request } = globalThis; class Client { readonly request = request; }",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports binding to the wrong receiver",
      filename: PRODUCTION,
      code: "const request = globalThis.fetch.bind(client);",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports computed binding to the wrong receiver",
      filename: PRODUCTION,
      code: "const request = globalThis.fetch['bind'](client);",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports calling with the wrong receiver",
      filename: PRODUCTION,
      code: "const response = fetch.call(client, url);",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    {
      name: "reports computed apply with the wrong receiver",
      filename: PRODUCTION,
      code: "const response = fetch['apply'](client, args);",
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
  ],
});
