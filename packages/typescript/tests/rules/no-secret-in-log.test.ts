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
  ],
});
