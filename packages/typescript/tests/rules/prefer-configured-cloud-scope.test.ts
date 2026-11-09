// vitest: shared-module-graph
import rule from "../../src/rules/prefer-configured-cloud-scope.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

RULE_TESTER.run("prefer-configured-cloud-scope", rule, {
  valid: [
    {
      name: "uses validated environment configuration",
      code: "import { env } from './env.js'; fetch(`https://api.cloudflare.com/client/v4/accounts/${env.CLOUDFLARE_ACCOUNT_ID}/workers/scripts`);",
    },
    {
      name: "accepts an injected account scope",
      code: "export function list(accountId, request = fetch) { return request(`https://api.cloudflare.com/client/v4/accounts/${accountId}/workers/scripts`); }",
    },
    {
      name: "preserves a security allowlist and expected identity schema",
      code: "const allowed = ['0123456789abcdef0123456789abcdef']; const expected = z.literal('0123456789abcdef0123456789abcdef'); fetch(`https://api.cloudflare.com/client/v4/accounts/${env.accountId}/workers/scripts`);",
    },
    {
      name: "preserves an expected account URL comparison",
      code: "if (url === 'https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts') throw new Error('unexpected target');",
    },
    {
      name: "does not infer an outgoing request from an unused URL string",
      code: "const url = 'https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts'; console.log(url);",
    },
    {
      name: "preserves the provider API origin",
      code: "fetch('https://api.cloudflare.com/client/v4/accounts');",
    },
    {
      name: "requires a real account-shaped segment rather than a placeholder",
      code: "fetch('https://api.cloudflare.com/client/v4/accounts/ACCOUNT_ID/workers/scripts');",
    },
    {
      name: "requires a complete account path segment",
      code: "fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef0/workers/scripts');",
    },
    {
      name: "does not confuse a foreign API with Cloudflare",
      code: "fetch('https://api.cloudflare.com.example.org/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts');",
    },
    {
      name: "preserves the case-sensitive API path",
      code: "fetch('https://api.cloudflare.com/CLIENT/v4/ACCOUNTS/0123456789abcdef0123456789abcdef/workers/scripts');",
    },
    {
      name: "does not infer an unproven transport from a parameter name",
      code: "function run(fetch) { return fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts'); }",
    },
    {
      name: "preserves an unrelated request-default parameter",
      code: "function run(request = readFixture) { return request('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts'); }",
    },
    {
      name: "does not infer native fetch from an import",
      code: "import fetch from './read-fixture.js'; fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts');",
    },
    {
      name: "does not follow mutable account bindings",
      code: "let accountId = '0123456789abcdef0123456789abcdef'; accountId = env.accountId; fetch(`https://api.cloudflare.com/client/v4/accounts/${accountId}/workers/scripts`);",
    },
    {
      name: "does not treat a partial account prefix as the whole account",
      code: "const prefix = '0123456789abcdef0123456789abcdef'; fetch(`https://api.cloudflare.com/client/v4/accounts/${prefix}${suffix}/workers/scripts`);",
    },
    {
      name: "does not infer a configured fallback",
      code: "const accountId = env.accountId ?? '0123456789abcdef0123456789abcdef'; fetch(`https://api.cloudflare.com/client/v4/accounts/${accountId}/workers/scripts`);",
    },
    {
      name: "does not recurse through cyclic constant definitions",
      code: "const first = second; const second = first; fetch(`https://api.cloudflare.com/client/v4/accounts/${first}/workers/scripts`);",
    },
    {
      name: "respects lexical account shadowing",
      code: "const accountId = '0123456789abcdef0123456789abcdef'; function run(accountId) { return fetch(`https://api.cloudflare.com/client/v4/accounts/${accountId}/workers/scripts`); }",
    },
    {
      name: "vetoes ambient fetch replacement even when later in source",
      code: "fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts'); globalThis.fetch = readFixture;",
    },
    {
      name: "vetoes deletion of the ambient fetch",
      code: "delete globalThis['fetch']; fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts');",
    },
    {
      name: "vetoes replacement of a global receiver through its global property",
      code: "globalThis.globalThis = { fetch: readFixture }; globalThis.fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts');",
    },
    {
      name: "vetoes destructured ambient fetch assignment",
      code: "({ fetch } = injected); fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts');",
    },
    {
      name: "vetoes an array-pattern global fetch assignment",
      code: "[globalThis.fetch] = [custom]; fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts');",
    },
    {
      name: "vetoes replacement of the global receiver",
      code: "globalThis = { fetch: readFixture }; globalThis.fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts');",
    },
    {
      name: "vetoes ambient fetch written by a for-of target",
      code: "for (fetch of callbacks) {} fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts');",
    },
    {
      name: "ignores comment and string examples",
      code: "// fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts');\nconst example = \"fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts')\";",
    },
    {
      name: "excludes test fixture identities",
      filename: "tests/publish.test.ts",
      code: "fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts');",
    },
    {
      name: "excludes generated source",
      filename: "src/generated/client.ts",
      code: "fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts');",
    },
  ],
  invalid: [
    {
      name: "reports an inline management URL",
      code: "fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts');",
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "reports the originating account constant through base and injected fetch-default parameter",
      filename: ".github/scripts/publish.mjs",
      code: "const accountId = '0123456789abcdef0123456789abcdef';\nconst base = `https://api.cloudflare.com/client/v4/accounts/${accountId}`;\nexport async function publish(path, request = fetch) { return request(`${base}/${path}`); }",
      errors: [{ messageId: "configuredScope", type: "Literal", line: 1, column: 19 }],
    },
    {
      name: "follows const aliases and concatenation",
      code: "const account = '0123456789abcdef0123456789abcdef'; const alias = account; const base = 'https://api.cloudflare.com/client/v4/accounts/' + alias; fetch(base + '/workers/scripts');",
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "reports an account embedded in a template quasi with a dynamic resource suffix",
      code: "fetch(`https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts/${name}`);",
      errors: [{ messageId: "configuredScope", type: "TemplateElement" }],
    },
    {
      name: "recognizes a stable const fetch alias",
      code: "const request = fetch; request('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts');",
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "recognizes bracket access to a native global receiver",
      code: "globalThis['fetch']('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts');",
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "does not duplicate findings for repeated use of the same literal",
      code: "const account = '0123456789abcdef0123456789abcdef'; const base = `https://api.cloudflare.com/client/v4/accounts/${account}`; fetch(base); fetch(`${base}/workers/scripts`);",
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "reports independent source account literals separately",
      code: "fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts'); fetch('https://api.cloudflare.com/client/v4/accounts/fedcba9876543210fedcba9876543210/workers/scripts');",
      errors: [{ messageId: "configuredScope", type: "Literal" }, { messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "follows erased TypeScript wrappers",
      code: "const account = '0123456789abcdef0123456789abcdef' as const; fetch(`https://api.cloudflare.com/client/v4/accounts/${account!}/workers/scripts` satisfies string);",
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "accepts an exact account segment before a query string",
      code: "fetch('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef?per_page=20');",
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
  ],
});
