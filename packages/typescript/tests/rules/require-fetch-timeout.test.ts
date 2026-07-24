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
    // Member-expression fetches are out of scope (Cloudflare service bindings,
    // custom clients).
    {
      code: "await env.MY_SERVICE.fetch(request);",
    },
    {
      code: "await client.fetch(url);",
    },
    // allowIn glob exempts wrapper modules.
    {
      code: "await fetch(url);",
      options: [{ allowIn: ["**/http-client.ts"] }],
      filename: "/repo/src/lib/http-client.ts",
    },
  ],
  invalid: [
    // No init argument at all.
    {
      code: "await fetch(url);",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      code: "const res = await fetch('https://api.example.com/v1/things');",
      errors: [{ messageId: "missingSignal" }],
    },
    // Object-literal init provably lacking a signal.
    {
      code: "await fetch(url, { method: 'POST', body });",
      errors: [{ messageId: "missingSignal" }],
    },
    {
      code: "await fetch(url, {});",
      errors: [{ messageId: "missingSignal" }],
    },
    // allowIn only exempts matching files.
    {
      code: "await fetch(url);",
      options: [{ allowIn: ["**/http-client.ts"] }],
      filename: "/repo/src/routes/page.ts",
      errors: [{ messageId: "missingSignal" }],
    },
  ],
});
