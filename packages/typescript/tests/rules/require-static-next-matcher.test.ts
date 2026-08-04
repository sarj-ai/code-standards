import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/require-static-next-matcher.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

const MIDDLEWARE = "/repo/src/middleware.ts";
const PROXY = "/repo/src/proxy.ts";

ruleTester.run("require-static-next-matcher", rule, {
  valid: [
    {
      name: "accepts a literal string matcher",
      code: `export const config = { matcher: "/api/:path*" };`,
      filename: MIDDLEWARE,
    },
    {
      name: "accepts a literal matcher array",
      code: `export const config = { matcher: ["/api/:path*", "/dashboard/:path*"] };`,
      filename: PROXY,
    },
    {
      name: "accepts fully static matcher objects",
      code: `export const config = {
        matcher: [{ source: "/api/:path*", locale: false, has: [{ type: "header", key: "x-ready", value: "yes" }] }],
      };`,
      filename: MIDDLEWARE,
    },
    {
      name: "accepts a non-interpolated matcher template",
      code: "export const config = { matcher: `/api/:path*` };",
      filename: MIDDLEWARE,
    },
    {
      name: "accepts a satisfies wrapper around static config",
      code: `export const config = {
        matcher: ["/api/:path*"],
      } satisfies MiddlewareConfig;`,
      filename: MIDDLEWARE,
    },
    {
      name: "ignores unrelated config objects",
      code: `export const config = { runtime: getRuntime() };`,
      filename: MIDDLEWARE,
    },
    {
      name: "ignores matcher properties outside Next entry files",
      code: `export const config = { matcher: String.raw\`/api\\.json\` };`,
      filename: "/repo/src/routes.ts",
    },
    {
      name: "ignores non-exported application objects",
      code: `const config = { matcher: getApplicationMatcher() };`,
      filename: MIDDLEWARE,
    },
  ],
  invalid: [
    {
      name: "rejects String.raw tagged templates",
      code: `export const config = { matcher: String.raw\`/api\\.json\` };`,
      filename: MIDDLEWARE,
      errors: [{ messageId: "dynamicMatcher" }],
    },
    {
      name: "rejects matcher identifiers",
      code: `const matcher = "/api/:path*"; export const config = { matcher };`,
      filename: MIDDLEWARE,
      errors: [{ messageId: "dynamicMatcher" }],
    },
    {
      name: "rejects matcher calls",
      code: `export const config = { matcher: createMatcher() };`,
      filename: PROXY,
      errors: [{ messageId: "dynamicMatcher" }],
    },
    {
      name: "rejects concatenated matcher strings",
      code: `export const config = { matcher: "/api/" + suffix };`,
      filename: MIDDLEWARE,
      errors: [{ messageId: "dynamicMatcher" }],
    },
    {
      name: "rejects interpolated matcher templates",
      code: "export const config = { matcher: `/api/${segment}` };",
      filename: MIDDLEWARE,
      errors: [{ messageId: "dynamicMatcher" }],
    },
    {
      name: "rejects array spreads",
      code: `export const config = { matcher: ["/api/:path*", ...extraMatchers] };`,
      filename: MIDDLEWARE,
      errors: [{ messageId: "dynamicMatcher" }],
    },
    {
      name: "rejects dynamic values nested in matcher objects",
      code: `export const config = { matcher: [{ source: routeSource, locale: false }] };`,
      filename: MIDDLEWARE,
      errors: [{ messageId: "dynamicMatcher" }],
    },
    {
      name: "rejects object spreads",
      code: `export const config = { matcher: [{ source: "/api/:path*", ...conditions }] };`,
      filename: MIDDLEWARE,
      errors: [{ messageId: "dynamicMatcher" }],
    },
  ],
});
