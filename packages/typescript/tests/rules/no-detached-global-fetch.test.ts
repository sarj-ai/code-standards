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
    { name: "allows a matching bound receiver", filename: PRODUCTION, code: "const request = globalThis.fetch.bind(globalThis);" },
    { name: "allows self binding", filename: PRODUCTION, code: "const request = self.fetch.bind(self);" },
    { name: "allows explicit call receiver", filename: PRODUCTION, code: "const response = fetch.call(globalThis, url, init);" },
    { name: "allows explicit apply receiver", filename: PRODUCTION, code: "const response = globalThis.fetch.apply(globalThis, args);" },
    { name: "allows a typeof reference", filename: PRODUCTION, code: "type Fetch = typeof fetch; let request: typeof globalThis.fetch;" },
    { name: "ignores a parameter", filename: PRODUCTION, code: "function client(fetch: typeof globalThis.fetch) { return fetch; }" },
    { name: "ignores an imported implementation", filename: PRODUCTION, code: "import fetch from 'node-fetch'; const request = fetch;" },
    { name: "ignores a local implementation", filename: PRODUCTION, code: "const fetch = makeRequest(); const request = fetch;" },
    { name: "ignores a shadowed receiver", filename: PRODUCTION, code: "function client(globalThis: Runtime) { return globalThis.fetch; }" },
    { name: "ignores object property names", filename: PRODUCTION, code: "const client = { fetch: request };" },
    { name: "ignores tests", filename: "/repo/apps/worker/test/client.test.ts", code: "const request = fetch;" },
    { name: "ignores scripts", filename: "/repo/scripts/probe.ts", code: "const request = fetch;" },
    { name: "ignores generated files", filename: "/repo/src/generated/client.ts", code: "const request = fetch;" },
  ],
  invalid: [
    {
      name: "reports the documented detached default",
      filename: PRODUCTION,
      code: NO_DETACHED_GLOBAL_FETCH_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "detachedGlobalFetch" }],
    },
    { name: "reports a stored ambient fetch", filename: PRODUCTION, code: "const request = fetch;", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports a returned ambient fetch", filename: PRODUCTION, code: "function request() { return fetch; }", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports a callback argument", filename: PRODUCTION, code: "registerTransport(fetch);", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports explicit globalThis capture", filename: PRODUCTION, code: "const request = globalThis.fetch;", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports explicit self capture", filename: PRODUCTION, code: "const request = self.fetch;", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports binding to the wrong receiver", filename: PRODUCTION, code: "const request = globalThis.fetch.bind(client);", errors: [{ messageId: "detachedGlobalFetch" }] },
    { name: "reports an uninvoked bind method", filename: PRODUCTION, code: "const binder = fetch.bind;", errors: [{ messageId: "detachedGlobalFetch" }] },
  ],
});
