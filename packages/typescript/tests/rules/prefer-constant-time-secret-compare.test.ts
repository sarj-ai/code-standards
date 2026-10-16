// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { PREFER_CONSTANT_TIME_SECRET_COMPARE_DOCUMENTATION } from "../../src/rules/prefer-constant-time-secret-compare.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

RULE_TESTER.run("prefer-constant-time-secret-compare", rule, {
  valid: [
    { name: "dynamic credential-header names remain opaque", code: "function check(req: Request, expected: string, key: string) { const given = req.headers.get(key); return given === expected; }" },
    { name: "transformed credential is not inferred sensitive", code: "function check(req: Request, expected: string) { const given = isAllowed(req.headers.get('authorization')); return given === expected; }" },
    { name: "request reassignment invalidates header provenance", code: "function check(req: Request, expected: string) { req = model; const given = req.headers.get('authorization'); return given === expected; }" },
    { name: "similarly named custom NextRequest remains opaque", code: "import {NextRequest} from './model'; function check(req: NextRequest, expected: string) { const given = req.headers.get('authorization'); return given === expected; }" },
    { name: "ordinary request header is not a credential", code: "function check(req: Request, expected: string) { const given = req.headers.get('accept'); return given === expected; }" },
    { name: "custom header-like object remains opaque", code: "function check(req, expected) { const given = req.headers.get('x-webhook-secret'); return given === expected; }" },
    { name: "reassigned generic credential alias remains opaque", code: "function check(req: Request, expected: string) { let given = req.headers.get('authorization'); given = label; return given === expected; }" },
    { name: "credential alias presence checks remain valid", code: "function check(req: Request) { const given = req.headers.get('authorization'); return given !== null; }" },
    { name: "credential metadata header remains valid", code: "function check(req: Request, expected: string) { const given = req.headers.get('x-token-type'); return given === expected; }" },
    { name: "locally shadowed Request annotation remains opaque", code: "type Request = {headers: {get(key: string): string}}; function check(req: Request, expected: string) { const given = req.headers.get('authorization'); return given === expected; }" },

    { name: "ordinary template header names remain public", code: 'function check(req: Request, expected: string) { return req.headers.get(`accept`) === expected; }' },
    { name: "interpolated credential header names remain opaque", code: 'function check(req: Request, expected: string, suffix: string) { return req.headers.get(`x-webhook-${suffix}`) === expected; }' },
    { name: "computed credential reads on arbitrary objects remain opaque", code: 'function check(req, expected) { return req.headers["get"](`x-webhook-secret`) === expected; }' },
    { name: "unresolved computed header methods remain opaque", code: 'function check(req: Request, expected: string, method: string) { return req.headers[method](`x-webhook-secret`) === expected; }' },

    { name: "does not confuse parser-token identity with authentication", code: "if (firstToken === lastToken || token !== startToken || currentToken !== finalToken) advance();" },
    { name: "does not confuse token navigation metadata with secret bytes", code: "if (firstTokenLine === secondTokenLine || tokenBefore === commentList[index - 1]) advance();" },
    { name: "leaves ambiguous token names to typed or domain-specific analysis", code: "if (token === expectedToken) consume();" },
    { name: "public no-match example", filename: PREFER_CONSTANT_TIME_SECRET_COMPARE_DOCUMENTATION.examples[0].focusPath, code: PREFER_CONSTANT_TIME_SECRET_COMPARE_DOCUMENTATION.examples[0].files[0].source },
    {
      name: "allows identity checks against a camelCase marker ending in Token",
      code: "if (options.queryFn === skipToken) { options.enabled = false; }",
    },
    {
      name: "allows nested identity checks against skipToken",
      code: "const disabled = defaultedOptions.queryFn === skipToken;",
    },
    {
      name: "allows identity checks against other marker prefixes",
      code: "if (value !== emptyToken) { use(value); }",
    },
    // --- Presence checks: comparing against a sentinel leaks nothing. ---
    { code: "if (token === null) { deny(); }" },
    { code: "if (token !== undefined) { use(token); }" },
    { code: "if (apiKey == null) { deny(); }" },
    { code: "if (secret.length === 0) { deny(); }" },
    // --- Compile-time literal sentinels: the attacker already knows the value. ---
    { code: 'if (tokenType === "Bearer") { parse(); }' },
    { code: 'if (scheme === "bearer") { parse(); }' },
    { code: "if (token === TOKEN_SENTINEL) { deny(); }" },
    { code: "if (secret === Sentinels.EMPTY_SECRET) { deny(); }" },
    {
      name: "allows a secret-shaped value compared with a public named constant",
      code: "if (token === TOKEN_TYPE_SYSTEM) { deny(); }",
    },
    { code: "if (grant === `client_credentials`) { deny(); }" },
    // --- Category / handle metadata, not the credential (SARJ011 narrowing). ---
    { code: "if (tokenType === other.tokenType) { merge(); }" },
    { code: "if (credentialKind === expectedKind) { merge(); }" },
    { code: "if (tokenName === other.tokenName) { merge(); }" },
    { code: "if (apiKeyId === row.apiKeyId) { merge(); }" },
    { code: "if (secretId === row.secretId) { merge(); }" },
    // --- Boolean flags: a decision, not the bytes. ---
    { code: "if (isTokenValid === wasTokenValid) { skip(); }" },
    { code: "if (hasSecret === other.hasSecret) { skip(); }" },
    // --- Counters / metadata that merely embed a secret word. ---
    { code: "if (tokenCount === previousTokenCount) { skip(); }" },
    { code: "if (promptTokens === completionTokens) { skip(); }" },
    { code: "if (passwordEnabled === other.passwordEnabled) { skip(); }" },
    // --- Integrity-only content hash: a change detector, not an authenticator. ---
    { code: "if (contentHash === previousHash) { skip(); }" },
    { code: "if (fileDigest === cachedDigest) { skip(); }" },
    // --- Not a secret at all. ---
    { code: "if (userId === other.userId) { merge(); }" },
    { code: "if (keyboardEvent === lastEvent) { skip(); }" },
    { code: "if (publicKey === other.publicKey) { skip(); }" },
    // AST node type constants can contain `Signature` but are enum values, not credentials.
    { code: "if (member.type !== AST_NODE_TYPES.TSPropertySignature) { return null; }" },
    // --- Ordering / relational operators are not equality short-circuits. ---
    { code: "if (token > other.token) { sort(); }" },
    // --- Computed access has no static property name to judge. ---
    { code: "if (config[name] === other[name]) { merge(); }" },
    // --- Test files: no attacker measures a test's clock. ---
    {
      code: 'if (result.apiKey === "known-fixture") { pass(); }',
      filename: "/repo/src/auth.test.ts",
    },
    {
      name: "allows secret comparisons in test files",
      code: 'if (result.apiKey === candidate) { pass(); }',
      filename: "/repo/test/auth-helpers.ts",
    },
  ],
  invalid: [
    { name: "imported NextRequest alias proves credential provenance", code: "import {NextRequest as Incoming} from 'next/server'; function check(req: Incoming, expected: string) { const given = req.headers.get('authorization'); return given === expected; }", errors: [{messageId: "preferConstantTimeSecretCompare"}] },
    { name: "constructed native Request proves credential provenance", code: "const req = new Request('/items'); const given = req.headers.get('authorization'); given === expected;", errors: [{messageId: "preferConstantTimeSecretCompare"}] },
    { name: "uppercase generic alias retains credential provenance", code: "function check(req: Request, expected: string) { const RECEIVED = req.headers.get('authorization'); return RECEIVED === expected; }", errors: [{messageId: "preferConstantTimeSecretCompare"}] },
    { name: "configuration secret survives a generic stable alias", code: "const expected = process.env.INTERNAL_AUTH_TOKEN; supplied === expected;", errors: [{messageId: "preferConstantTimeSecretCompare"}] },
    { name: "explicit credential header survives generic local names", code: "function check(req: Request, expected: string) { const given = req.headers.get('x-webhook-secret'); return given === expected; }", errors: [{messageId: "preferConstantTimeSecretCompare"}] },
    { name: "authorization credential survives a stable alias", code: "function check(req: Request, expected: string) { const given = req.headers.get('authorization'); const candidate = given; return candidate !== expected; }", errors: [{messageId: "preferConstantTimeSecretCompare"}] },
    { name: "credential header fallback preserves credential provenance", code: "function check(req: Request, expected: string) { const given = req.headers.get('x-api-key') ?? new URL(req.url).searchParams.get('key'); return given === expected; }", errors: [{messageId: "preferConstantTimeSecretCompare"}] },
    { name: "direct credential header comparison is checked", code: "function check(req: Request, expected: string) { return req.headers.get('authorization') === expected; }", errors: [{messageId: "preferConstantTimeSecretCompare"}] },

    { name: "retains credential provenance from a no-substitution template header", code: 'function check(req: Request, expected: string) { const given = req.headers.get(`x-webhook-secret`); return given === expected; }', errors: [{ messageId: "preferConstantTimeSecretCompare" }] },
    { name: "retains credential provenance through a const header assertion", code: 'function check(req: Request, expected: string) { const given = req.headers.get(("x-webhook-secret" as const)); return given === expected; }', errors: [{ messageId: "preferConstantTimeSecretCompare" }] },
    { name: "recognizes static computed native header access", code: 'function check(req: Request, expected: string) { return req["headers"]["get"](`x-webhook-secret`) === expected; }', errors: [{ messageId: "preferConstantTimeSecretCompare" }] },

    { name: "public match example", filename: PREFER_CONSTANT_TIME_SECRET_COMPARE_DOCUMENTATION.examples[1].focusPath, code: PREFER_CONSTANT_TIME_SECRET_COMPARE_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "preferConstantTimeSecretCompare" }] },
    // The sentinel prefix list must stay narrow: a live credential still fires.
    {
      name: "requires a runtime-supported primitive without prescribing a nonexistent WebCrypto method",
      code: "if (req.headers.apiKey === env.apiKey) { allow(); }",
      errors: [
        {
          message:
            "`===` on secret-like `apiKey` is not guaranteed constant-time. Use a constant-time comparison primitive supported by the target runtime and handle its input-length requirements.",
        },
      ],
    },
    // The live shape: an admin bearer token compared with `===`.
    {
      code: "if (presented === expectedAccessToken) { await next(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    // SCREAMING_SNAKE secrets. These regressed once: the ALL-CAPS carve-out for
    // public named constants (`TOKEN_TYPE_SYSTEM`) swallowed every real secret,
    // because environment secrets are conventionally ALL-CAPS too. The rule was
    // silent on all of these while firing on their camelCase equivalents, so a
    // clean run proved nothing. Keep these pinned.
    {
      code: "if (token === env.INTERNAL_ADMIN_TOKEN) { await next(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    {
      code: "if (sig !== env.SLACK_SIGNING_SECRET) { return unauthorized(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    {
      code: "if (key === process.env.ASHBY_API_KEY) { allow(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    {
      code: "const { INTERNAL_ADMIN_TOKEN } = env; if (token === INTERNAL_ADMIN_TOKEN) { allow(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    {
      code: "if (header !== `Bearer ${env.internalAdminToken}`) { return unauthorized(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    // Webhook signature verification, the other classic timing leak.
    {
      code: "if (signature !== computed) { return reject(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    {
      code: "if (expectedHmac === receivedHmac) { accept(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    // Member-expression operands.
    {
      code: "if (req.apiKey === env.apiKey) { allow(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    {
      code: "if (user.passwordHash === candidateHash) { login(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    // Loose equality is no better.
    {
      code: "if (token == suppliedAccessToken) { allow(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    {
      code: "if (clientSecret != storedSecret) { deny(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    // snake_case spelling decomposes the same way.
    {
      code: "if (api_key === presented_key) { allow(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    // A JWT string compare is still a credential compare.
    {
      code: "if (jwt === cachedJwt) { reuse(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    // A leading flag word does not make it metadata — the trailing token rules.
    {
      code: "if (validToken === presentedAccessToken) { allow(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    // `tokenHash` gates access, unlike a bare content hash.
    {
      code: "if (tokenHash === storedTokenHash) { allow(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
  ],
});
