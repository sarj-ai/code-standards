import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  noCorsWildcardWithCredentialsDocumentation,
} from "../../src/rules/no-cors-wildcard-with-credentials.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-cors-wildcard-with-credentials", rule, {
  valid: [
    // Wildcard origin WITHOUT credentials — safe (browser blocks credentialed
    // wildcard anyway). This is a real first-party CORS shape.
    { code: "app.use(cors({ origin: '*' }));" },
    {
      code: "const CORS = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'POST, GET, OPTIONS' };",
    },
    { code: "res.setHeader('Access-Control-Allow-Origin', '*');" },
    // Credentials WITH a specific origin — safe.
    {
      code: noCorsWildcardWithCredentialsDocumentation.examples[0].files[0].source,
    },
    {
      code: "app.use(cors({ origin: ['https://a.example.com', 'https://b.example.com'], credentials: true }));",
    },
    {
      code: "const CORS = { 'Access-Control-Allow-Origin': 'https://app.example.com', 'Access-Control-Allow-Credentials': 'true' };",
    },
    // credentials: false with wildcard — safe.
    { code: "app.use(cors({ origin: '*', credentials: false }));" },
    // A `"*"` string unrelated to CORS.
    { code: "const glob = '*';" },
    { code: "const pattern = { match: '*' };" },
    // Only one manual header (origin wildcard) with credentials for a DIFFERENT
    // origin value — the ACAC set is not "true".
    {
      code: "res.setHeader('Access-Control-Allow-Origin', '*'); res.setHeader('Access-Control-Allow-Credentials', 'false');",
    },
    // Wildcard origin and credentials=true set in SEPARATE function scopes —
    // must not pair up across scopes.
    {
      code: "function a() { res.setHeader('Access-Control-Allow-Origin', '*'); } function b() { res.setHeader('Access-Control-Allow-Credentials', 'true'); }",
    },
    // Separate response receivers in one function must not pair either.
    {
      code: "function h(originResponse, credentialsResponse) { originResponse.setHeader('Access-Control-Allow-Origin', '*'); credentialsResponse.setHeader('Access-Control-Allow-Credentials', 'true'); }",
    },
    // credentials=true header alone.
    { code: "res.setHeader('Access-Control-Allow-Credentials', 'true');" },
    // Non-cors call named something else with a wildcard+credentials-shaped
    // object should still be safe when keys are unrelated.
    { code: "configure({ origin: '*', credentials: true });" },
    // origin is a validator FUNCTION (echoes the request origin) with
    // credentials — no `"*"` literal, safe.
    {
      code: "app.use(cors({ origin: (origin, callback) => callback(null, true), credentials: true }));",
    },
    {
      code: "app.use(cors({ origin: function (origin, cb) { cb(null, origin); }, credentials: true }));",
    },
    // origin is a RegExp (source text has `*`, but the literal value is a
    // RegExp, not the string `"*"`) with credentials — safe.
    {
      code: "app.use(cors({ origin: /https:\\/\\/.*\\.example\\.com$/, credentials: true }));",
    },
    // origin is a dynamic variable/array reference with credentials — safe.
    {
      code: "app.use(cors({ origin: allowedOrigins, credentials: true }));",
    },
    // origin is a template literal with credentials — safe.
    {
      code: "app.use(cors({ origin: `${base}.example.com`, credentials: true }));",
    },
    // A wildcard ROUTE/glob (`path: '*'`) alongside an unrelated `credentials`
    // flag — not a CORS header object, not a cors() call. Safe.
    { code: "const route = { path: '*', credentials: true };" },
    { code: "router.get('*', handler);" },
    // Header object that pairs wildcard origin with a NON-credentials header —
    // safe.
    {
      code: "const headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Credentials': 'false' };",
    },
    // cors() with wildcard origin and NO credentials key — the common safe case.
    { code: "app.use(cors({ origin: '*', methods: ['GET', 'POST'] }));" },
    // credentials value is a non-true expression on a wildcard cors() — safe.
    { code: "app.use(cors({ origin: '*', credentials: isProd }));" },
    // setHeader wildcard origin paired with a credentials set whose value is a
    // variable (not literally true) — safe.
    {
      code: "res.setHeader('Access-Control-Allow-Origin', '*'); res.setHeader('Access-Control-Allow-Credentials', allowCreds);",
    },
  ],
  invalid: [
    // cors() bare "*" origin + credentials.
    {
      code: noCorsWildcardWithCredentialsDocumentation.examples[1].files[0].source,
      errors: [{ messageId: "corsWildcardWithCredentials" }],
    },
    // cors() array ["*"] origin + credentials.
    {
      code: "app.use(cors({ origin: ['*'], credentials: true }));",
      errors: [{ messageId: "corsWildcardWithCredentials" }],
    },
    // cors() conditional "*" branch + credentials.
    {
      code: "app.use(cors({ origin: isDev ? allowed : '*', credentials: true }));",
      errors: [{ messageId: "corsWildcardWithCredentials" }],
    },
    // new Cors(...) form.
    {
      code: "const c = new Cors({ origin: '*', credentials: true });",
      errors: [{ messageId: "corsWildcardWithCredentials" }],
    },
    // Two-header object literal.
    {
      code: "const headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Credentials': 'true' };",
      errors: [{ messageId: "corsWildcardWithCredentials" }],
    },
    // Case-insensitive header names in object literal.
    {
      code: "const headers = { 'access-control-allow-origin': '*', 'access-control-allow-credentials': 'TRUE' };",
      errors: [{ messageId: "corsWildcardWithCredentials" }],
    },
    // NextResponse header object literal.
    {
      code: "return new NextResponse(body, { headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Credentials': 'true' } });",
      errors: [{ messageId: "corsWildcardWithCredentials" }],
    },
    // setHeader pair in the same scope.
    {
      code: "res.setHeader('Access-Control-Allow-Origin', '*'); res.setHeader('Access-Control-Allow-Credentials', 'true');",
      errors: [{ messageId: "corsWildcardWithCredentials" }],
    },
    // headers.set pair in the same function scope.
    {
      code: "function h() { headers.set('Access-Control-Allow-Origin', '*'); headers.set('Access-Control-Allow-Credentials', 'true'); }",
      errors: [{ messageId: "corsWildcardWithCredentials" }],
    },
    {
      name: "pairs the same resolved static member receiver",
      code: "function h(response) { response.headers.set('Access-Control-Allow-Origin', '*'); response.headers.set('Access-Control-Allow-Credentials', 'true'); }",
      errors: [{ messageId: "corsWildcardWithCredentials" }],
    },
    {
      name: "rejects wildcard credentials set with headers.append",
      code: "headers.append('Access-Control-Allow-Origin', '*'); headers.append('Access-Control-Allow-Credentials', 'true');",
      errors: [{ messageId: "corsWildcardWithCredentials" }],
    },
    {
      name: "matches manual header names without case sensitivity",
      code: "res.setHeader('ACCESS-CONTROL-ALLOW-ORIGIN', '*'); res.setHeader('Access-Control-Allow-Credentials', 'TRUE');",
      errors: [{ messageId: "corsWildcardWithCredentials" }],
    },
    // Boolean-coerced credentials value on setHeader.
    {
      code: "res.setHeader('Access-Control-Allow-Origin', '*'); res.setHeader('Access-Control-Allow-Credentials', true);",
      errors: [{ messageId: "corsWildcardWithCredentials" }],
    },
  ],
});
