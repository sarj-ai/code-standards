import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { noInsecureRandomIdDocumentation } from "../../src/rules/no-insecure-random-id.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-insecure-random-id", rule, {
  valid: [
    { code: noInsecureRandomIdDocumentation.examples[0].files[0].source },
    // Bare `Math.random()` for jitter — not an identifier.
    { code: "const jitter = Math.random() * 100;" },
    // Sampling / probability roll.
    { code: "if (Math.random() < 0.5) doThing();" },
    { code: "const sample = Math.random();" },
    { code: "const roll = Math.floor(Math.random() * 6) + 1;" },
    // A `.toString(36)` on something that is NOT Math.random() is fine.
    { code: "const hex = (255).toString(16);" },
    { code: "const label = value.toString(36);" },
    // `.toString` with a non-36 radix on Math.random() is not the flagged idiom
    // and the binding name is non-sensitive.
    { code: "const ratio = Math.random().toString();" },
    { code: "const ratio = Math.random().toString(10);" },
    // The prescribed secure replacements.
    { code: "const id = crypto.randomUUID();" },
    {
      code: "const key = crypto.getRandomValues(new Uint8Array(16));",
    },
    // Sensitive-sounding name but no Math.random() involved.
    { code: "const token = generateToken();" },
    // Math.random() whose enclosing name is not sensitive.
    { code: "const opacity = Math.random();" },
    { code: "const delayMs = Math.random() * 1000;" },
    // Math.random() in a property with a non-sensitive name.
    { code: "const cfg = { jitter: Math.random() };" },
    {
      code: "const tempPath = filePath + '.tmp.' + Math.random().toString(36).slice(2);",
    },
    {
      code: "const sessionId = Math.floor(Number.MAX_SAFE_INTEGER * Math.random());",
    },
    { code: "const executionId = 'exec-' + Math.random().toString(36);" },
    { code: "const requestId = Math.random().toString(16);" },
    { code: "const session = Math.random();" },
    { code: "class ContextIdFactory { private readonly session = Math.random(); }" },
    // Bare `id`/`key`/`session` substrings alone no longer fire — we require a
    // strong security signal and err toward suppressing ambiguous ids.
    { code: "const id = Math.random();" },
    { code: "const obj = { sessionId: Math.random() };" },
    // Random value concatenated into a path — even the toString(36) idiom is
    // suppressed here.
    { code: "const output = base + '/tmp/' + Math.random().toString(36);" },
    {
      code: "class Mocker { get string() { return Math.random().toString(36).substring(7); } }",
      filename: "src/v3/tests/Mocker.ts",
    },
    {
      code: "const m = { [Math.random().toString(36).slice(2)]: 1 };",
      filename: "__tests__/vendor/turbo-stream-test.ts",
    },
    {
      code: "const apiToken = Math.random().toString(36);",
      filename: "src/auth.test.ts",
    },
  ],
  invalid: [
    { code: noInsecureRandomIdDocumentation.examples[1].files[0].source, errors: [{ messageId: "insecureRandomId" }] },
    // Trigger 1: classic `.toString(36)` insecure id idiom.
    {
      code: "const x = Math.random().toString(36).slice(2);",
      errors: [{ messageId: "insecureRandomId" }],
    },
    {
      code: "const x = Math.random().toString(36);",
      errors: [{ messageId: "insecureRandomId" }],
    },
    {
      code: "const x = Math.random().toString(36).substring(2, 15);",
      errors: [{ messageId: "insecureRandomId" }],
    },
    // toString(36) idiom even when the binding name is innocuous.
    {
      code: "const value = Math.random().toString(36).slice(2);",
      errors: [{ messageId: "insecureRandomId" }],
    },
    // Genuine security-token shapes with the toString(36) idiom stay flagged.
    {
      code: "const token = Math.random().toString(36);",
      errors: [{ messageId: "insecureRandomId" }],
    },
    {
      code: "const csrfToken = Math.random().toString(36).slice(2);",
      errors: [{ messageId: "insecureRandomId" }],
    },
    // Trigger 1 (name-based): strong security name — variable declarators.
    {
      code: "const apiKey = Math.random();",
      errors: [{ messageId: "insecureRandomId" }],
    },
    {
      code: "const userSecret = Math.random();",
      errors: [{ messageId: "insecureRandomId" }],
    },
    {
      code: "const uuid = Math.random();",
      errors: [{ messageId: "insecureRandomId" }],
    },
    {
      code: "const nonce = Math.random();",
      errors: [{ messageId: "insecureRandomId" }],
    },
    {
      code: "const password = Math.random();",
      errors: [{ messageId: "insecureRandomId" }],
    },
    {
      code: "const salt = Math.random();",
      errors: [{ messageId: "insecureRandomId" }],
    },
    // Name-based even with surrounding arithmetic.
    {
      code: "const token = `t-${Math.random()}`;",
      errors: [{ messageId: "insecureRandomId" }],
    },
    // Strong security name in an object property key.
    {
      code: "const obj = { 'access-token': Math.random() };",
      errors: [{ messageId: "insecureRandomId" }],
    },
    // Strong security name in a class property definition.
    {
      code: "class S { token = Math.random(); }",
      errors: [{ messageId: "insecureRandomId" }],
    },

    // The very same idiom in production code still fires — the exemption is
    // scoped to the path, not to the shape.
    {
      code: "const m = { [Math.random().toString(36).slice(2)]: 1 };",
      filename: "src/serialize.ts",
      errors: [{ messageId: "insecureRandomId" }],
    },
  ],
});

ruleTester.run("no-insecure-random-id security-name contract", rule, {
  valid: [],
  invalid: [
    {
      code: "const token = Math.random();",
      errors: [{ messageId: "insecureRandomId" }],
    },
    {
      code: "const secret = Math.random();",
      errors: [{ messageId: "insecureRandomId" }],
    },
    {
      code: "const csrf = Math.random();",
      errors: [{ messageId: "insecureRandomId" }],
    },
    {
      code: "const passwd = Math.random();",
      errors: [{ messageId: "insecureRandomId" }],
    },
    {
      code: "const api_key = Math.random();",
      errors: [{ messageId: "insecureRandomId" }],
    },
    {
      code: "const authId = Math.random();",
      errors: [{ messageId: "insecureRandomId" }],
    },
  ],
});

ruleTester.run("no-insecure-random-id non-security-name exceptions", rule, {
  valid: [
    { code: "const tempId = Math.random().toString(36);" },
    { code: "const tmpId = Math.random().toString(36);" },
    { code: "const cacheKey = Math.random().toString(36);" },
    { code: "const correlationId = Math.random().toString(36);" },
    { code: "const reqId = Math.random().toString(36);" },
    { code: "const traceId = Math.random().toString(36);" },
    { code: "const devId = Math.random().toString(36);" },
    { code: "const hmrId = Math.random().toString(36);" },
    { code: "const mockId = Math.random().toString(36);" },
    { code: "const testId = Math.random().toString(36);" },
    { code: "const perfMarker = Math.random().toString(36);" },
    { code: "const key = Math.random();" },
  ],
  invalid: [
    {
      code: "const requestToken = Math.random();",
      errors: [{ messageId: "insecureRandomId" }],
    },
  ],
});

ruleTester.run("no-insecure-random-id path and DOM exceptions", rule, {
  valid: [
    { code: "const output = `tmp/${Math.random().toString(36)}`;" },
    { code: "const output = `tmp\\\\${Math.random().toString(36)}`;" },
    { code: "const output = `#row-${Math.random().toString(36)}`;" },
    { code: "const output = `asset-${Math.random().toString(36)}.js`;" },
  ],
  invalid: [
    {
      code: "const authId = `#row-${Math.random()}`;",
      errors: [{ messageId: "insecureRandomId" }],
    },
  ],
});

ruleTester.run("no-insecure-random-id production-file boundary", rule, {
  valid: [
    {
      code: "const token = Math.random().toString(36);",
      filename: "src/auth.spec.ts",
    },
  ],
  invalid: [
    {
      code: "const token = Math.random().toString(36);",
      filename: "src/auth.ts",
      errors: [{ messageId: "insecureRandomId" }],
    },
  ],
});

ruleTester.run("no-insecure-random-id arithmetic-chain limitation", rule, {
  valid: [{ code: "const x = (Math.random() * 1e9).toString(36);" }],
  invalid: [
    {
      code: "const token = (Math.random() * 1e9).toString(36);",
      errors: [{ messageId: "insecureRandomId" }],
    },
  ],
});
