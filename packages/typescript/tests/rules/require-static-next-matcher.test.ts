// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  REQUIRE_STATIC_NEXT_MATCHER_DOCUMENTATION,
} from "../../src/rules/require-static-next-matcher.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

const MIDDLEWARE = "/repo/src/middleware.ts";
const PROXY = "/repo/src/proxy.ts";

RULE_TESTER.run("require-static-next-matcher", rule, {
  valid: [
    {
      name: "accepts the documented literal matcher",
      code: REQUIRE_STATIC_NEXT_MATCHER_DOCUMENTATION.examples[0].files[0]
        .source,
      filename: REQUIRE_STATIC_NEXT_MATCHER_DOCUMENTATION.examples[0].focusPath,
    },
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
    {
      name: "ignores unrelated computed config keys",
      code: `export const config = { ["runtime"]: getRuntime() };`,
      filename: MIDDLEWARE,
    },
  ],
  invalid: [
    {
      name: "refuses erased private route declarations",
      code: 'declare const matcher = "/api/:path*"; export const config = { matcher };',
      output: null,
      errors: [{ messageId: "dynamicMatcher" }],
      filename: "/repo/src/middleware.ts",
    },
    {
      name: "refuses erased config declarations",
      code: 'const matcher = "/api/:path*"; export declare const config = { matcher };',
      output: null,
      errors: [{ messageId: "dynamicMatcher" }],
      filename: "/repo/src/middleware.ts",
    },
    {
      name: "retains other exported config properties",
      code: 'const matcher = "/api/:path*"; export const config = { matcher, runtime: "nodejs" };',
      filename: "/repo/src/middleware.ts",
      errors: [{ messageId: "dynamicMatcher" }],
      output: null,
    },
    {
      name: "retains array allocation ownership",
      code: 'const matcher = ["/api/:path*"]; export const config = { matcher };',
      filename: "/repo/src/middleware.ts",
      errors: [{ messageId: "dynamicMatcher" }],
      output: null,
    },
    {
      name: "retains annotated route contracts",
      code: 'const matcher: string = "/api/:path*"; export const config = { matcher };',
      filename: "/repo/src/middleware.ts",
      errors: [{ messageId: "dynamicMatcher" }],
      output: null,
    },
    {
      name: "retains annotated exported config",
      code: 'const matcher = "/api/:path*"; export const config: {matcher:string} = { matcher };',
      filename: "/repo/src/middleware.ts",
      errors: [{ messageId: "dynamicMatcher" }],
      output: null,
    },
    {
      name: "retains immutable assertion contracts",
      code: 'const matcher = "/api/:path*"; export const config = { matcher } as const;',
      filename: "/repo/src/middleware.ts",
      errors: [{ messageId: "dynamicMatcher" }],
      output: null,
    },
    {
      name: "retains source imports",
      code: 'import "setup"; const matcher = "/api/:path*"; export const config = { matcher };',
      filename: "/repo/src/middleware.ts",
      errors: [{ messageId: "dynamicMatcher" }],
      output: null,
    },
    {
      name: "retains additional route readers",
      code: 'const matcher = "/api/:path*"; export const config = { matcher }; consume(matcher);',
      filename: "/repo/src/middleware.ts",
      errors: [{ messageId: "dynamicMatcher" }],
      output: null,
    },
    {
      name: "retains mutable route bindings",
      code: 'let matcher = "/api/:path*"; export const config = { matcher };',
      filename: "/repo/src/middleware.ts",
      errors: [{ messageId: "dynamicMatcher" }],
      output: null,
    },
    {
      name: "retains comments and directives",
      code: 'const matcher = "/api/:path*"; /* route contract */ export const config = { matcher };',
      filename: "/repo/src/middleware.ts",
      errors: [{ messageId: "dynamicMatcher" }],
      output: null,
    },
    {
      name: "retains computed matcher keys",
      code: 'const matcher = "/api/:path*"; export const config = { ["matcher"]: matcher };',
      filename: "/repo/src/middleware.ts",
      errors: [{ messageId: "dynamicMatcher" }],
      output: null,
    },
    {
      name: "retains other declaration effects",
      code: 'const matcher = "/api/:path*", extra = observe(); export const config = { matcher };',
      filename: "/repo/src/middleware.ts",
      errors: [{ messageId: "dynamicMatcher" }],
      output: null,
    },
    {
      name: "retains exported route names",
      code: 'export const matcher = "/api/:path*"; export const config = { matcher };',
      filename: "/repo/src/middleware.ts",
      errors: [{ messageId: "dynamicMatcher" }],
      output: null,
    },
    {
      name: "reports the documented computed matcher",
      code: REQUIRE_STATIC_NEXT_MATCHER_DOCUMENTATION.examples[1].files[0]
        .source,
      filename: REQUIRE_STATIC_NEXT_MATCHER_DOCUMENTATION.examples[1].focusPath,
      errors: [{ messageId: "dynamicMatcher" }],
      output: 'export const config = { matcher: "/api/:path*" };',
    },
    {
      name: "inlines the existing route into a longhand matcher",
      code: 'const route = "/dashboard/:path*"; export const config = { "matcher": route };',
      filename: PROXY,
      errors: [{ messageId: "dynamicMatcher" }],
      output: 'export const config = { "matcher": "/dashboard/:path*" };',
    },
    {
      name: "retains CRLF inside the exported declaration",
      code: 'const route = "/api/:path*";\r\nexport const config = {\r\n  matcher: route,\r\n};\r\n',
      filename: MIDDLEWARE,
      errors: [{ messageId: "dynamicMatcher" }],
      output: 'export const config = {\r\n  matcher: "/api/:path*",\r\n};\r\n',
    },
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
      output: 'export const config = { matcher: "/api/:path*" };',
    },
    {
      name: "rejects matcher calls",
      code: `export const config = { matcher: createMatcher() };`,
      filename: PROXY,
      errors: [{ messageId: "dynamicMatcher" }],
    },
    {
      name: "rejects dynamic values behind a computed literal matcher key",
      code: `export const config = { ["matcher"]: createMatcher() };`,
      filename: MIDDLEWARE,
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
