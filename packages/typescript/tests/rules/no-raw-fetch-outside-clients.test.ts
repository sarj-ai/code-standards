import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-raw-fetch-outside-clients.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

/** A path outside the client layer, where a raw fetch must be reported. */
const HANDLER = "/repo/src/routes/handler.ts";

ruleTester.run("no-raw-fetch-outside-clients", rule, {
  valid: [
    // --- Allowed by the default path patterns -------------------------------
    {
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/clients/slack-client.ts",
    },
    {
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/client/index.ts",
    },
    {
      code: "export const get = () => fetch(url);",
      filename: "/repo/packages/shared/src/http-client.ts",
    },
    {
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/lib/ashby-client.ts",
    },
    {
      code: "it('works', () => fetch(url));",
      filename: "/repo/src/routes/handler.test.ts",
    },
    {
      code: "it('works', () => fetch(url));",
      filename: "/repo/src/routes/handler.spec.ts",
    },
    {
      code: "it('works', () => fetch(url));",
      filename: "/repo/src/__tests__/handler.ts",
    },
    // --- Not the global fetch ----------------------------------------------
    // A `fetch` method on an unrelated receiver is not outbound HTTP.
    { code: "const rows = cache.fetch(key);", filename: HANDLER },
    { code: "const d = queryClient.fetch();", filename: HANDLER },
    // Going through a client is the whole point of the rule.
    { code: "const r = await slackClient.postMessage(c, t);", filename: HANDLER },
    // A computed member access we cannot resolve statically.
    { code: "const r = api['fetch'](url);", filename: HANDLER },
    // A local binding shadowing nothing global, on a non-global receiver.
    { code: "const r = this.fetch(url);", filename: HANDLER },
    // --- Custom allow list ---------------------------------------------------
    {
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/lib/api/gateway.ts",
      options: [{ allow: ["[\\\\/]lib[\\\\/]api[\\\\/]"] }],
    },
    // An unparseable pattern is skipped, and the remaining one still exempts.
    {
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/gateway.ts",
      options: [{ allow: ["([unterminated", "gateway\\.ts$"] }],
    },
  ],
  invalid: [
    // Bare global fetch in a route handler.
    {
      code: "export const handler = () => fetch('https://example.test');",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    // Explicit global receivers.
    {
      code: "const r = globalThis.fetch(url);",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    {
      code: "const r = window.fetch(url);",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    {
      code: "const r = self.fetch(url);",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }],
    },
    // Each call site is reported independently.
    {
      code: "const a = fetch(one); const b = fetch(two);",
      filename: HANDLER,
      errors: [{ messageId: "rawFetch" }, { messageId: "rawFetch" }],
    },
    // A custom `allow` REPLACES the defaults, so a client path is no longer
    // exempt unless the consumer keeps the pattern.
    {
      code: "export const get = () => fetch(url);",
      filename: "/repo/src/clients/slack-client.ts",
      options: [{ allow: ["[\\\\/]lib[\\\\/]api[\\\\/]"] }],
      errors: [{ messageId: "rawFetch" }],
    },
  ],
});
