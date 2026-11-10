// vitest: shared-module-graph
import rule from "../../src/rules/prefer-configured-cloud-scope.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

RULE_TESTER.run("prefer-configured-cloud-scope", rule, {
  valid: [
    {
      name: "a type-wrapped global capture can replace the URL constructor",
      code: 'const globals = globalThis as typeof globalThis; globals.URL = class {} as typeof URL; fetch(new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"));',
    },
    {
      name: "a non-null wrapped global URL capture can mutate the prototype",
      code: 'const Constructor = (globalThis!).URL; Constructor.prototype.toString = () => "https://example.test/fixture"; fetch(new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"));',
    },
    {
      name: "a satisfies-wrapped global capture is still a runtime capability",
      code: 'const globals = globalThis satisfies typeof globalThis; globals.URL = LocalURL; fetch(new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"));',
    },
    {
      name: "a wrapped global receiver parameter remains a foreign runtime object",
      code: 'function run(globalThis) { return fetch(new (globalThis!).URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts")); }',
    },
    {
      name: "a wrapped foreign receiver is not inferred to be native globalThis",
      code: 'fetch(new (injected as typeof globalThis).URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"));',
    },
    {
      name: "wrapped writes to the native fetch retain the direct-fetch veto",
      code: '(globalThis as typeof globalThis).fetch = readFixture; fetch("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts");',
    },
    {
      name: "escaping the global receiver can expose URL to an alias mutator",
      code: "const globals = globalThis; globals.URL = LocalURL; fetch(new URL('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts'));",
    },
    {
      name: "dynamic global code makes native URL semantics unknown",
      code: "eval('URL = LocalURL'); fetch(new URL('https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts'));",
    },
    {
      name: "a local URL constructor does not establish native URL semantics",
      code: 'function run(URL) { return fetch(new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts")); }',
    },
    {
      name: "an imported URL constructor is outside the native wrapper proof",
      code: 'import { URL } from "./custom-url.js"; fetch(new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"));',
    },
    {
      name: "replacing the ambient URL constructor vetoes wrapper folding",
      code: 'globalThis.URL = LocalURL; fetch(new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"));',
    },
    {
      name: "mutating the URL prototype vetoes wrapper folding",
      code: 'URL.prototype.toString = () => "fixture"; fetch(new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"));',
    },
    {
      name: "passing the URL constructor to an arbitrary mutator vetoes wrapper folding",
      code: 'Object.defineProperty(URL, "custom", { value: true }); fetch(new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"));',
    },
    {
      name: "a configured account remains dynamic inside a native URL",
      code: "fetch(new URL(`https://api.cloudflare.com/client/v4/accounts/${settings.CLOUDFLARE_ACCOUNT_ID}/workers/scripts`));",
    },
    {
      name: "native URL objects used only as independent expected identities remain policy",
      code: 'const expected = new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"); if (actual.href !== expected.href) throw new Error("unexpected target");',
    },
    {
      name: "relative-base URL construction remains unreported",
      code: 'fetch(new URL("/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts", "https://api.cloudflare.com"));',
    },
    {
      name: "a mutable URL instance cannot retain its original account proof",
      code: 'const endpoint = new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"); endpoint.pathname = "/fixture"; fetch(endpoint);',
    },
    {
      name: "an exported URL instance can be mutated by another module",
      code: 'export const endpoint = new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"); fetch(endpoint);',
    },
    {
      name: "an injected transport may mutate a stored URL object",
      code: 'const endpoint = new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"); export function run(request = fetch) { return request(endpoint); }',
    },
    {
      name: "URL normalization must not move the selected account segment",
      code: 'fetch(new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/../workers/scripts"));',
    },
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
      name: "an unchanged native URL may use a type-wrapped global receiver",
      code: 'fetch(new (globalThis as typeof globalThis).URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"));',
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "an unchanged native URL may use a non-null wrapped global receiver",
      code: 'fetch(new (globalThis!).URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"));',
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "transparent global receiver wrappers preserve direct fetch findings",
      code: '(globalThis! as typeof globalThis).fetch("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts");',
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "a wrapped URL capture does not hide independent direct string findings",
      code: 'const globals = globalThis as typeof globalThis; globals.URL = LocalURL; fetch(new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts")); fetch("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts");',
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "a type-only global reference is not a runtime constructor escape",
      code: 'type Globals = typeof globalThis; fetch(new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"));',
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "reports an inline unchanged native absolute URL wrapper",
      code: 'fetch(new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"));',
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "reports a stored native URL read only by direct native fetch calls once",
      code: 'const endpoint = new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"); fetch(endpoint); globalThis.fetch(endpoint);',
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "recognizes a native global URL constructor without widening the API scope",
      code: 'fetch(new globalThis.URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts"));',
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
    {
      name: "a URL replacement does not hide independent direct fetch findings",
      code: 'globalThis.URL = LocalURL; fetch(new URL("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts")); fetch("https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/workers/scripts");',
      errors: [{ messageId: "configuredScope", type: "Literal" }],
    },
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
      errors: [
        { messageId: "configuredScope", type: "Literal" },
        { messageId: "configuredScope", type: "Literal" },
      ],
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
