import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-constant-time-secret-compare.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("prefer-constant-time-secret-compare", rule, {
  valid: [
    // FP guard, corpus: query/packages/query-core/src/queryClient.ts:604 (10 of
    // 10 hits) — `skipToken` is a marker Symbol compared by identity.
    { code: "if (options.queryFn === skipToken) { options.enabled = false; }" },
    { code: "const disabled = defaultedOptions.queryFn === skipToken;" },
    { code: "if (value !== emptyToken) { use(value); }" },
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
      code: 'if (result.apiKey === candidate) { pass(); }',
      filename: "/repo/test/auth-helpers.ts",
    },
  ],
  invalid: [
    // The sentinel prefix list must stay narrow: a live credential still fires.
    {
      code: "if (req.headers.apiKey === env.apiKey) { allow(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    // The live shape: an admin bearer token compared with `===`.
    {
      code: "if (presented === expectedToken) { await next(); }",
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
      code: "if (token == suppliedToken) { allow(); }",
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
      code: "if (validToken === presentedToken) { allow(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
    // `tokenHash` gates access, unlike a bare content hash.
    {
      code: "if (tokenHash === storedTokenHash) { allow(); }",
      errors: [{ messageId: "preferConstantTimeSecretCompare" }],
    },
  ],
});
