import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-secret-in-log.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-secret-in-log", rule, {
  valid: [
    // Innocuous trailing token: usage counter, not the secret.
    { code: 'logger.info("usage", { tokenCount });' },
    // Row-id of a key, not the key material.
    { code: 'logger.info("key", { apiKeyId });' },
    // Discriminator, not the credential.
    { code: 'logger.debug("auth", { tokenType });' },
    // Boolean feature flag, not the credential.
    { code: 'logger.warn("cfg", { passwordEnabled });' },
    // Boolean presence flag.
    { code: 'logger.info("auth", { tokenPresent });' },
    // Redaction markers are the intended safe form.
    { code: 'logger.info("auth", { tokenPrefix });' },
    { code: 'logger.info("auth", { apiKeyTag });' },
    { code: 'logger.info("auth", { passwordHash });' },
    { code: 'logger.info("auth", { tokenLength });' },
    // Non-secret payload.
    { code: 'logger.info("user", { userId });' },
    { code: 'logger.info("req", { requestId, durationMs });' },
    // Non-logger receiver: not a logging call.
    { code: 'metrics.info("x", { token });' },
    { code: 'db.error("q", { password });' },
    // Not a log-level method on a logger.
    { code: 'logger.child({ token });' },
    // Bare non-secret positional identifier.
    { code: 'logger.info("hello", user);' },
    // `secretary` embeds `secret` only as a substring — whole-token clears it.
    { code: 'logger.info("sec", { secretary });' },
    // Pluralized `tokens` counter is not the singular secret word.
    { code: 'logger.info("usage", { promptTokens, completionTokens });' },
    // console is a logger, but innocuous names still do not fire.
    { code: 'console.log("usage", { tokenCount });' },
    { code: 'console.error("user", { userId });' },
    // Secret word appears mid-identifier but the trailing token is a metadata
    // descriptor — this is data ABOUT a secret, not the secret value.
    { code: 'logger.info("santa", { secretSantaName });' },
    { code: 'logger.info("key", { apiKeyLabel });' },
    { code: 'logger.info("auth", { refreshTokenExpiry });' },
    { code: 'logger.info("auth", { tokenExpiry });' },
    { code: 'logger.info("auth", { tokenExpiresAt });' },
    { code: 'logger.info("auth", { passwordChangedAt });' },
    { code: 'logger.info("auth", { secretVersion });' },
    { code: 'logger.info("aws", { secretArn });' },
    { code: 'logger.info("sm", { secretPath });' },
    { code: 'logger.info("oauth", { tokenIssuer, tokenAudience });' },
    { code: 'logger.info("oauth", { tokenScopes });' },
    { code: 'logger.info("oauth", { tokenUrl });' },
    { code: 'logger.info("cfg", { passwordPolicy });' },
    { code: 'logger.info("cfg", { passwordStrength });' },
    { code: 'logger.info("di", { apiKeyService, credentialProvider });' },
    { code: 'logger.info("di", { secretStore, apiKeyManager });' },
    { code: 'logger.info("rate", { tokenBucket });' },
    // Non-secret compounds that merely embed a secret word as a substring.
    { code: 'logger.info("kbd", { keyboardEvent });' },
    { code: 'logger.info("auth", { passwordless });' },
    { code: 'logger.info("crypto", { publicKey });' },
    { code: 'logger.info("cfg", { keyName });' },
    // Logging length / presence of a secret is the safe form.
    { code: 'logger.info("auth", { tokenLen });' },
    { code: 'logger.info("auth", secret.length);' },
    { code: 'logger.info("auth", token.length);' },
    // Member-expression args whose last segment is innocuous stay valid.
    { code: 'logger.info("user", user.name);' },
    { code: 'logger.info("user", config.apiKeyId);' },
    { code: 'logger.info("auth", config.tokenPrefix);' },
    // Computed member access has no static property name to match.
    { code: 'logger.info("auth", config[secret]);' },
    // String literal that merely mentions the word — not an identifier value.
    { code: 'logger.info("api key rotated");' },
    { code: 'logger.warn("password reset requested for user");' },
    // Redacted object-property values: the key is secret-named but the VALUE is
    // already truncated / masked / a placeholder, so nothing sensitive leaks.
    { code: 'logger.info("cfg", { apiKey: config.apiKey ? `${config.apiKey.substring(0, 10)}...` : "(missing)" });' },
    { code: 'logger.info("auth", { token: token.slice(0, 6) });' },
    { code: 'logger.info("auth", { password: mask(password) });' },
    { code: 'logger.info("auth", { secret: redact(secret) });' },
    { code: 'logger.info("auth", { apiKey: "***" });' },
    { code: 'logger.info("auth", { token: `${token.slice(0, 4)}...` });' },
    { code: 'logger.info("auth", { credentials: hasCreds ? "set" : "unset" });' },
    // An UNDECLARED free function is not assumed to be a log sink.
    { code: 'logEvent("slack.auth", { botToken });' },
    // A declared logger still respects the innocuous-name and redaction rules.
    {
      code: 'logEvent("slack.auth", { tokenPrefix });',
      options: [{ logFunctions: ["logEvent"] }],
    },

    // A LEADING boolean-predicate word makes the name a flag answering "does a
    // secret exist?", which leaks nothing. Mirrors the trailing innocuous-word
    // guard; both now live in the shared `isSecretName`.
    {
      code: 'logEvent("s", { hasSecret });',
      options: [{ logFunctions: ["logEvent"] }],
    },
    { code: "logger.info({ isToken });" },
    { code: "log.info({ has_secret });" },
    { code: "log.info({ is_token });" },
    { code: 'logger.info("auth", { isTokenStrategy, wasPasswordReset });' },
    { code: "logger.info(hasApiKey);" },
    // `hash_secret` IS a secret to the shared predicate — `hash` is a whole word,
    // not the prefix `has` — but this rule exempts every `hash` name via its own
    // REDACTION_RE, the same clause that keeps the pinned `passwordHash` valid.
    // Its firing behaviour is therefore owned by `prefer-constant-time-secret-compare`,
    // not by the leading-flag guard.
    { code: 'logger.info("auth", { hash_secret });' },

    // ---- raw-blob arm: the exemptions that keep it adoptable ----
    // A narrowed FIELD of a body is the fix, not the defect — the member
    // property decides, never the object it was picked from.
    { code: 'logger.info("resp", { id: body.id });' },
    { code: 'logger.info("resp", { bodyLength: body.length });' },
    { code: 'logger.info("resp", { status: res.status, issueCount: body.issues.length });' },
    { code: 'logger.info("resp", { payloadId: payload.id });' },
    // Passed through a redactor / summariser: the SHAPE is the exemption, so any
    // project's own summariser qualifies without being enumerated.
    { code: 'logger.info("resp", { body: redact(body) });' },
    { code: 'logger.info("resp", { body: sanitize(body) });' },
    { code: 'logger.info("resp", { body: pick(body, ["id", "status"]) });' },
    { code: 'logger.info("resp", { body: JSON.stringify(body).slice(0, 200) });' },
    { code: 'logger.info("resp", { payload: summarizeIssues(payload) });' },
    { code: "logger.info(redact(res.body));" },
    // Already a rendered string / template, not the blob.
    { code: 'logger.info("resp", { body: "ok" });' },
    { code: 'logger.info("resp", { body: `status=${res.status}` });' },
    { code: 'logger.info("resp", { body: res.ok ? "ok" : "failed" });' },
    // Redaction / derivation markers in the NAME.
    { code: 'logger.info("resp", { redactedBody });' },
    { code: 'logger.info("resp", { sanitizedPayload });' },
    { code: 'logger.info("resp", { truncatedBody });' },
    { code: 'logger.info("resp", { maskedPayload });' },
    { code: 'logger.info("resp", { bodyHash });' },
    { code: 'logger.info("resp", { bodyPreview });' },
    { code: 'logger.info("resp", { payloadSummary });' },
    { code: 'logger.info("resp", { safeBody });' },
    { code: 'logger.info("resp", { bodySize, paramsCount });' },
    // Boolean flags about a blob, not the blob.
    { code: 'logger.info("resp", { hasBody });' },
    { code: 'logger.info("resp", { isPayload });' },
    // Generic container words are NOT blob words — firing on these is what would
    // get the rule switched off.
    { code: 'logger.info("x", { data });' },
    { code: 'logger.info("x", { input, args, result });' },
    { code: 'logger.info("x", { event, record, item });' },
    { code: 'logger.info("x", { req, res });' },
    // Metadata whose trailing word is not a blob word.
    { code: 'logger.info("x", { bodyType, paramsSchema });' },
    // Spread is deliberately out of scope for this arm.
    { code: 'logger.info("resp", { ...body });' },
    // Not a logging call at all.
    { code: 'metrics.record("resp", { body });' },
    { code: "res.send({ body });" },
    // A free function is not a log sink until the project declares it — the blob
    // arm honours `logFunctions` exactly like the secret arm.
    { code: 'logEvent("ashby.response", { body });' },
    // Bodies in a test file are fixtures the author wrote, not production PII.
    {
      code: 'logger.info("resp", { body });',
      filename: "src/ashby.test.ts",
    },
    {
      code: "console.log(res.body);",
      filename: "tests/fixtures/ashby.ts",
    },
    {
      name: "ignores computed member access because the property is not statically known",
      code: 'logger.info("resp", res["body"]);',
    },
  ],
  invalid: [
    // Object property: shorthand secret names.
    {
      code: 'logger.error("failed", { token });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    {
      code: 'logger.info("auth", { apiKey });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    {
      code: 'logger.warn("login", { password });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    // camelCase whole-token secret.
    {
      code: 'logger.debug("oauth", { clientSecret });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    {
      code: 'logger.info("oauth", { authToken });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    // Explicit key: value form.
    {
      code: 'logger.error("failed", { apiKey: theKey });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    // Bare secret-named positional identifier.
    {
      code: 'logger.info("x", secret);',
      errors: [{ messageId: "noSecretInLog" }],
    },
    // Trailing `key` preceded by a secret word is real secret material — the
    // metadata-descriptor exemption must not swallow this.
    {
      code: 'logger.error("cfg", { secretKey });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    // Real credential value with a non-descriptor trailing token still fires.
    {
      code: 'logger.info("auth", { secretValue });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    // Raw member-access value carries the secret verbatim — still fires.
    {
      code: 'logger.info("auth", { token: config.token });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    // Builder/factory chains still resolve to a logger.
    {
      code: 'logging.getLogger("x").info("auth", { jwt });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    {
      code: 'logger.bind({ id }).error("auth", { credentials });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    {
      code: 'this.logger.error("auth", { signature });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    // console is the JS-idiomatic logger.
    {
      code: 'console.error("failed", { token });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    // Multiple secret properties in one object → one report each.
    {
      code: 'logger.error("failed", { token, apiKey });',
      errors: [
        { messageId: "noSecretInLog" },
        { messageId: "noSecretInLog" },
      ],
    },
    // Member-expression positional args whose property is secret material — the
    // most common real logging shape.
    {
      code: 'logger.info("cfg", config.apiSecret);',
      errors: [{ messageId: "noSecretInLog" }],
    },
    {
      code: 'logger.error("login", user.password);',
      errors: [{ messageId: "noSecretInLog" }],
    },
    {
      code: 'logger.warn("auth", this.jwt);',
      errors: [{ messageId: "noSecretInLog" }],
    },
    // FP-1 security hole: a structured logger is a FREE FUNCTION, so this call
    // was never even examined before. Declaring it closes the hole.
    {
      code: 'logEvent("slack.auth", { botToken });',
      options: [{ logFunctions: ["logEvent"] }],
      errors: [{ messageId: "noSecretInLog" }],
    },
    // A declared logger RECEIVER name resolves like `logger` / `console`.
    {
      code: 'obs.error("auth", { apiKey });',
      options: [{ loggerNames: ["obs"] }],
      errors: [{ messageId: "noSecretInLog" }],
    },

    // The leading-flag exemption matches a whole WORD, never a character prefix,
    // so these credentials keep firing (`issuer` != `is`, `canary` != `can`).
    // `hash_secret` is pinned in the shared-predicate tests instead: this rule's
    // own REDACTION_RE exempts every `hash` name, deliberately and separately.
    {
      code: 'logger.info("oauth", { issuer_token });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    {
      code: 'logger.info("probe", { canary_token });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    {
      code: 'logger.info("cfg", { api_key, auth_token, slack_signing_secret });',
      errors: [
        { messageId: "noSecretInLog" },
        { messageId: "noSecretInLog" },
        { messageId: "noSecretInLog" },
      ],
    },
    {
      code: 'logger.info("cfg", { INTERNAL_ADMIN_TOKEN });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    {
      name: "still rejects secrets in test files",
      code: 'logger.info("auth", { token });',
      filename: "src/auth.test.ts",
      errors: [{ messageId: "noSecretInLog" }],
    },

    // ---- raw-blob arm: the coverage the GritQL plugin used to own ----
    // The shape the port was blocked on: a whole response body threaded into a
    // structured logger's meta object. No property here is secret-NAMED.
    {
      code: 'logEvent("ashby.response", { status: res.status, body });',
      options: [{ logFunctions: ["logEvent"] }],
      errors: [{ messageId: "noRawBodyInLog" }],
    },
    {
      code: 'logEvent("webhook.received", { rawBody });',
      options: [{ logFunctions: ["logEvent"] }],
      errors: [{ messageId: "noRawBodyInLog" }],
    },
    // Renaming the blob onto another key does not launder it.
    {
      code: 'logEvent("webhook.received", { meta: body });',
      options: [{ logFunctions: ["logEvent"] }],
      errors: [{ messageId: "noRawBodyInLog" }],
    },
    // A member access whose PROPERTY is the blob.
    {
      code: 'logger.info("resp", { body: res.body });',
      errors: [{ messageId: "noRawBodyInLog" }],
    },
    // Bare positional blob — the console shape the grit never covered.
    { code: "console.log(res.body);", errors: [{ messageId: "noRawBodyInLog" }] },
    { code: 'logger.debug("req", payload);', errors: [{ messageId: "noRawBodyInLog" }] },
    // The rest of the enumerated blob words.
    {
      code: 'logger.warn("req", { requestBody });',
      errors: [{ messageId: "noRawBodyInLog" }],
    },
    {
      code: 'logger.info("resp", { responsePayload });',
      errors: [{ messageId: "noRawBodyInLog" }],
    },
    {
      name: "rejects plural body names",
      code: 'logger.info("batch", { responseBodies });',
      errors: [{ messageId: "noRawBodyInLog" }],
    },
    {
      name: "rejects plural payload names",
      code: 'logger.info("batch", { webhookPayloads });',
      errors: [{ messageId: "noRawBodyInLog" }],
    },
    {
      code: 'logger.info("hook", { webhookPayload });',
      errors: [{ messageId: "noRawBodyInLog" }],
    },
    {
      code: 'logger.info("route", { searchParams });',
      errors: [{ messageId: "noRawBodyInLog" }],
    },
    {
      code: 'logger.info("upload", { formData });',
      errors: [{ messageId: "noRawBodyInLog" }],
    },
    // `safe` is only a redaction marker as a WHOLE token.
    {
      code: 'logger.info("resp", { unsafeBody });',
      errors: [{ messageId: "noRawBodyInLog" }],
    },
    // A declared logger RECEIVER carries the blob arm too.
    {
      code: 'obs.error("resp", { body });',
      options: [{ loggerNames: ["obs"] }],
      errors: [{ messageId: "noRawBodyInLog" }],
    },
    // Two blobs in one meta object → one report each.
    {
      code: 'logger.error("proxy", { requestBody, responseBody });',
      errors: [{ messageId: "noRawBodyInLog" }, { messageId: "noRawBodyInLog" }],
    },
    // A name that is BOTH secret-shaped and blob-shaped reports once, as the
    // secret — that advice is the more specific of the two.
    {
      code: 'logger.info("auth", { tokenBody });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    // Both arms can fire on the same call, one report each.
    {
      code: 'logEvent("ashby.call", { apiKey, body });',
      options: [{ logFunctions: ["logEvent"] }],
      errors: [{ messageId: "noSecretInLog" }, { messageId: "noRawBodyInLog" }],
    },
  ],
});
