// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_SECRET_IN_LOG_DOCUMENTATION } from "../../src/rules/no-secret-in-log.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

RULE_TESTER.run("no-secret-in-log", rule, {
  valid: [
    { name: "an array replacer may allowlist safe fields", code: "logger.info(JSON.stringify(body, ['id']));" },
    { name: "a function replacer may redact sensitive fields", code: "logger.info(JSON.stringify({token}, redact));" },
    { name: "an unknown replacer stays opaque through truncation", code: "logger.info(JSON.stringify(body, replacer).slice(0, 100));" },
    { name: "a shadowed JSON serializer may redact", code: "function log(JSON) { logger.info(JSON.stringify(body)); }" },
    { name: "a shadowed undefined may be a replacer", code: "function log(undefined) { logger.info(JSON.stringify(body, undefined)); }" },
    { name: "spread arguments make serializer positions unknown", code: "logger.info(JSON.stringify(...args));" },
    { name: "a redactor stays opaque through truncation", code: "logger.info(redact(body).slice(0, 100));" },
    { name: "truncated ordinary text remains safe", code: "logger.info(title.slice(0, 100));" },
    { name: "serialized public fields remain safe", code: "logger.info(JSON.stringify({id, count}));" },
    { name: "equal slice bounds expose no bytes", code: "logger.info(token.slice(0, 0));" },
    { name: "equal substring bounds expose no bytes", code: "logger.info(token.substring(2, 2));" },
    { name: "zero substr length exposes no bytes", code: "logger.info(body.substr(0, 0));" },
    { name: "serialized empty truncation exposes no bytes", code: "logger.info(JSON.stringify(body).slice(0, 0));" },
    { name: "serialization respects effective literal overrides", code: "logger.info(JSON.stringify({token, ...{token: maskedToken}}));" },
    { name: "raw-body fixture exemption survives serialization", code: "logger.info(JSON.stringify(body).slice(0, 100));", filename: "src/request.test.ts" },
    { code: 'logEvent("slack.auth", { botToken });' },
    {
      code: "console.log(res.body);",
      filename: "tests/fixtures/ashby.ts",
    },

    { name: "a computed logger method preserves redacted values", code: "logger['info']({ token: maskedToken });" },
    { name: "a computed logger method keeps a custom serializer opaque", code: "logger['info'](JSON['stringify']({ token }, redact));" },
    { name: "computed truncation with equal bounds exposes no bytes", code: "logger['info'](apiToken['slice'](0, 0));" },
    { name: "computed calls on an unconfigured receiver are not logging", code: "metrics['info'](apiToken);" },
    { name: "an unresolved computed logging method stays opaque", code: "logger[method]({ token });" },
    { name: "a shadowed computed serializer remains opaque", code: "function log(JSON) { logger['info'](JSON['stringify'](body)); }" },
    {
      name: "ignores an unresolved computed body property",
      code: 'logger.info("resp", res[property]);',
    },

    { name: "respects an explicitly redacted property value", code: "logger.info('auth', { token: redactedToken });" },
    { name: "respects a redacted member value under a secret key", code: "logger.info('auth', { token: result.maskedToken });" },
    { name: "accepts the documented redaction", code: NO_SECRET_IN_LOG_DOCUMENTATION.examples[0].files[0].source },


    { code: 'logger.info("usage", { tokenCount });' },

    { code: 'logger.info("key", { apiKeyId });' },

    { code: 'logger.debug("auth", { tokenType });' },

    { code: 'logger.warn("cfg", { passwordEnabled });' },

    { code: 'logger.info("auth", { tokenPresent });' },

    { code: 'logger.info("auth", { tokenPrefix });' },
    { code: 'logger.info("auth", { apiKeyTag });' },
    { code: 'logger.info("auth", { passwordHash });' },
    { code: 'logger.info("auth", { tokenLength });' },

    { code: 'logger.info("user", { userId });' },
    { code: 'logger.info("req", { requestId, durationMs });' },

    { code: 'metrics.info("x", { token });' },
    { code: 'db.error("q", { password });' },

    { code: 'logger.child({ token });' },

    { code: 'logger.info("hello", user);' },

    { code: 'logger.info("sec", { secretary });' },

    { code: 'logger.info("usage", { promptTokens, completionTokens });' },

    { code: 'console.log("usage", { tokenCount });' },
    { code: 'console.error("user", { userId });' },


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

    { code: 'logger.info("kbd", { keyboardEvent });' },
    { code: 'logger.info("auth", { passwordless });' },
    { code: 'logger.info("crypto", { publicKey });' },
    { code: 'logger.info("cfg", { keyName });' },

    { code: 'logger.info("auth", { tokenLen });' },
    { code: 'logger.info("auth", secret.length);' },
    { code: 'logger.info("auth", token.length);' },

    { code: 'logger.info("user", user.name);' },
    { code: 'logger.info("user", config.apiKeyId);' },
    { code: 'logger.info("auth", config.tokenPrefix);' },

    { code: 'logger.info("auth", config[secret]);' },

    { code: 'logger.info("api key rotated");' },
    { code: 'logger.warn("password reset requested for user");' },


    { code: 'logger.info("cfg", { apiKey: config.apiKey ? `${config.apiKey.substring(0, 10)}...` : "(missing)" });' },

    { code: 'logger.info("auth", { password: mask(password) });' },
    { code: 'logger.info("auth", { secret: redact(secret) });' },
    { code: 'logger.info("auth", { apiKey: "***" });' },

    { code: 'logger.info("auth", { credentials: hasCreds ? "set" : "unset" });' },



    {
      code: 'logEvent("slack.auth", { tokenPrefix });',
      options: [{ logFunctions: ["logEvent"] }],
    },




    {
      code: 'logEvent("s", { hasSecret });',
      options: [{ logFunctions: ["logEvent"] }],
    },
    { code: "logger.info({ isToken });" },
    { code: "log.info({ has_secret });" },
    { code: "log.info({ is_token });" },
    { code: 'logger.info("auth", { isTokenStrategy, wasPasswordReset });' },
    { code: "logger.info(hasApiKey);" },




    { code: 'logger.info("auth", { hash_secret });' },



    { code: 'logger.info("resp", { id: body.id });' },
    { code: 'logger.info("editor", await editor.text());' },
    { code: 'logger.info("resp", { bodyLength: body.length });' },
    { code: 'logger.info("resp", { status: res.status, issueCount: body.issues.length });' },
    { code: 'logger.info("resp", { payloadId: payload.id });' },


    { code: 'logger.info("resp", { body: redact(body) });' },
    { code: 'logger.info("resp", { body: sanitize(body) });' },
    { code: 'logger.info("resp", { body: pick(body, ["id", "status"]) });' },

    { code: 'logger.info("resp", { payload: summarizeIssues(payload) });' },
    { code: "logger.info(redact(res.body));" },

    { code: 'logger.info("resp", { body: "ok" });' },
    { code: 'logger.info("resp", { body: `status=${res.status}` });' },
    { code: 'logger.info("resp", { body: res.ok ? "ok" : "failed" });' },

    { code: 'logger.info("resp", { redactedBody });' },
    { code: 'logger.info("resp", { sanitizedPayload });' },
    { code: 'logger.info("resp", { truncatedBody });' },
    { code: 'logger.info("resp", { maskedPayload });' },
    { code: 'logger.info("resp", { bodyHash });' },
    { code: 'logger.info("resp", { bodyPreview });' },
    { code: 'logger.info("resp", { payloadSummary });' },
    { code: 'logger.info("resp", { safeBody });' },
    { code: 'logger.info("auth", { token: redactedToken });' },
    { code: 'logger.info("auth", `${token.length}`);' },
    { code: 'logger.info("auth", { token: redactedToken, ...{ token: maskedToken } });' },
    { code: 'logger.info("auth", { token, ...unknownFields });' },
    { code: 'logger.info("resp", { bodySize, paramsCount });' },

    { code: 'logger.info("resp", { hasBody });' },
    { code: 'logger.info("resp", { isPayload });' },


    { code: 'logger.info("x", { data });' },
    { code: 'logger.info("x", { input, args, result });' },
    { code: 'logger.info("x", { event, record, item });' },
    { code: 'logger.info("x", { req, res });' },

    { code: 'logger.info("x", { bodyType, paramsSchema });' },

    { code: 'logger.info("resp", { ...body });' },

    { code: 'metrics.record("resp", { body });' },
    { code: "res.send({ body });" },


    { code: 'logEvent("ashby.response", { body });' },

    {
      code: 'logger.info("resp", { body });',
      filename: "src/ashby.test.ts",
    },

    {
      name: "ignores unknown member access",
      code: 'logger.info("resp", res[member]);',
    },
  ],
  invalid: [
    { name: "a token prefix still exposes secret material", code: 'logger.info("auth", { token: token.slice(0, 6) });', errors: [{ messageId: "noSecretInLog" }] },
    { name: "a rendered token prefix still exposes secret material", code: 'logger.info("auth", { token: `${token.slice(0, 4)}...` });', errors: [{ messageId: "noSecretInLog" }] },
    { name: "serialization and truncation do not redact a body", code: 'logger.info("resp", { body: JSON.stringify(body).slice(0, 200) });', errors: [{ messageId: "noRawBodyInLog" }] },
    { name: "a substring exposes a secret member", code: 'logger.info(config.apiKey.substring(0, 10));', errors: [{ messageId: "noSecretInLog" }] },
    { name: "a substr exposes a raw body", code: 'logger.info(response.body.substr(0, 200));', errors: [{ messageId: "noRawBodyInLog" }] },
    { name: "a preview property does not hide direct raw-body provenance", code: 'logger.info({bodyPreview: body.slice(0, 200)});', errors: [{ messageId: "noRawBodyInLog" }] },
    { name: "serialization without an effective replacer exposes a secret", code: 'logger.info(JSON.stringify({token}, null, 2));', errors: [{ messageId: "noSecretInLog" }] },
    { name: "global undefined is not a replacer", code: 'logger.info(JSON.stringify(body, undefined));', errors: [{ messageId: "noRawBodyInLog" }] },
    { name: "void is not a replacer", code: 'logger.info(JSON.stringify(body, void 0));', errors: [{ messageId: "noRawBodyInLog" }] },
    { name: "nested truncation reports the source once", code: 'logger.info(JSON.stringify({tokenBody}).slice(0, 200).substring(0, 10));', errors: [{ messageId: "noSecretInLog" }] },
    { name: "reversed substring bounds still expose material", code: 'logger.info(token.substring(10, 0));', errors: [{ messageId: "noSecretInLog" }] },

    { name: "a computed logger method still exposes a credential field", code: "logger['info']({ token: apiToken }, 'request');", errors: [{ messageId: "noSecretInLog" }] },
    { name: "a computed logger method preserves serialization and truncation analysis", code: "logger['info'](JSON.stringify(body).slice(0, 200));", errors: [{ messageId: "noRawBodyInLog" }] },
    { name: "a computed logger method preserves token-prefix analysis", code: "logger['info']({ token: token.slice(0, 6) });", errors: [{ messageId: "noSecretInLog" }] },
    { name: "a computed native serializer preserves nested credential analysis", code: "logger['info'](JSON['stringify']({ token }, null));", errors: [{ messageId: "noSecretInLog" }] },
    { name: "erased casts preserve a computed logging call", code: "((logger as Logger)['info'] as LogMethod)({ token });", errors: [{ messageId: "noSecretInLog" }] },
    { name: "a computed credential property still exposes the value", code: "logger['info'](config['apiToken']);", errors: [{ messageId: "noSecretInLog" }] },

    { name: "reports static bracket access to the whole response body", code: 'logger.info("resp", res["body"]);', errors: [{ messageId: "noRawBodyInLog" }] },
    { name: "unmasked is not a redaction", code: 'logger.info("auth", { unmaskedToken });', errors: [{ messageId: "noSecretInLog" }] },
    { name: "unredacted is not a redaction", code: 'logger.info("request", { unredactedBody });', errors: [{ messageId: "noRawBodyInLog" }] },
    { name: "unsafe secret value under a secret key", code: 'logger.info("auth", { token: unmaskedToken });', errors: [{ messageId: "noSecretInLog" }] },
    { name: "template interpolation logs the token", code: 'logger.info("auth", `${token}`);', errors: [{ messageId: "noSecretInLog" }] },
    { name: "string concatenation logs the token", code: 'logger.info("auth: " + token);', errors: [{ messageId: "noSecretInLog" }] },
    { name: "literal spread logs the token", code: 'logger.info("auth", { ...{ token } });', errors: [{ messageId: "noSecretInLog" }] },
    { name: "nested literal logs the token", code: 'logger.info("auth", { context: { token } });', errors: [{ messageId: "noSecretInLog" }] },
    { name: "literal array logs the token", code: 'logger.info("auth", [token]);', errors: [{ messageId: "noSecretInLog" }] },
    { name: "later unsafe value replaces redacted value", code: 'logger.info("auth", { token: redactedToken, ...{ token } });', errors: [{ messageId: "noSecretInLog" }] },
    { name: "detects a secret value under an innocuous key", code: "logger.info('auth', { value: token });", errors: [{ messageId: "noSecretInLog" }] },
    { name: "detects a secret member value under an innocuous key", code: "logger.info('auth', { value: request.apiKey });", errors: [{ messageId: "noSecretInLog" }] },
    {
      name: "rejects a directly parsed response body",
      code: 'console.error("request failed", await response.text());',
      errors: [{ messageId: "noRawBodyInLog" }],
    },
    { name: "reports the documented secret", code: NO_SECRET_IN_LOG_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "noSecretInLog" }] },

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

    {
      code: 'logger.debug("oauth", { clientSecret });',
      errors: [{ messageId: "noSecretInLog" }],
    },
    {
      code: 'logger.info("oauth", { authToken });',
      errors: [{ messageId: "noSecretInLog" }],
    },

    {
      code: 'logger.error("failed", { apiKey: theKey });',
      errors: [{ messageId: "noSecretInLog" }],
    },

    {
      code: 'logger.info("x", secret);',
      errors: [{ messageId: "noSecretInLog" }],
    },


    {
      code: 'logger.error("cfg", { secretKey });',
      errors: [{ messageId: "noSecretInLog" }],
    },

    {
      code: 'logger.info("auth", { secretValue });',
      errors: [{ messageId: "noSecretInLog" }],
    },

    {
      code: 'logger.info("auth", { token: config.token });',
      errors: [{ messageId: "noSecretInLog" }],
    },

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

    {
      code: 'console.error("failed", { token });',
      errors: [{ messageId: "noSecretInLog" }],
    },

    {
      code: 'logger.error("failed", { token, apiKey });',
      errors: [
        { messageId: "noSecretInLog" },
        { messageId: "noSecretInLog" },
      ],
    },


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


    {
      code: 'logEvent("slack.auth", { botToken });',
      options: [{ logFunctions: ["logEvent"] }],
      errors: [{ messageId: "noSecretInLog" }],
    },

    {
      code: 'obs.error("auth", { apiKey });',
      options: [{ loggerNames: ["obs"] }],
      errors: [{ messageId: "noSecretInLog" }],
    },





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

    {
      code: 'logEvent("webhook.received", { meta: body });',
      options: [{ logFunctions: ["logEvent"] }],
      errors: [{ messageId: "noRawBodyInLog" }],
    },

    {
      code: 'logger.info("resp", { body: res.body });',
      errors: [{ messageId: "noRawBodyInLog" }],
    },

    { code: "console.log(res.body);", errors: [{ messageId: "noRawBodyInLog" }] },
    { code: 'logger.debug("req", payload);', errors: [{ messageId: "noRawBodyInLog" }] },

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

    {
      code: 'logger.info("resp", { unsafeBody });',
      errors: [{ messageId: "noRawBodyInLog" }],
    },

    {
      code: 'obs.error("resp", { body });',
      options: [{ loggerNames: ["obs"] }],
      errors: [{ messageId: "noRawBodyInLog" }],
    },

    {
      code: 'logger.error("proxy", { requestBody, responseBody });',
      errors: [{ messageId: "noRawBodyInLog" }, { messageId: "noRawBodyInLog" }],
    },


    {
      code: 'logger.info("auth", { tokenBody });',
      errors: [{ messageId: "noSecretInLog" }],
    },

    {
      code: 'logEvent("ashby.call", { apiKey, body });',
      options: [{ logFunctions: ["logEvent"] }],
      errors: [{ messageId: "noSecretInLog" }, { messageId: "noRawBodyInLog" }],
    },
  ],
});


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "logged-secret-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "src/auth.ts",
    "expectedCount": 1,
    "files": [
      {
        "path": "src/auth.ts",
        "source": "logger[\"error\"]('auth failed', { token });"
      }
    ]
  },
  {
    "id": "logged-secret-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "src/auth.ts",
    "expectedCount": 0,
    "files": [
      {
        "path": "src/auth.ts",
        "source": "logger[auditDynamicMember]('auth failed', { token });"
      }
    ]
  }
] } });
});
