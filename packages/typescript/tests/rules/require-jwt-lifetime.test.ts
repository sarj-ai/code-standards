// vitest: shared-module-graph
import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { REQUIRE_JWT_LIFETIME_DOCUMENTATION } from "../../src/rules/require-jwt-lifetime.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser } });
TESTER.run("require-jwt-lifetime", rule, {
  valid: [
    REQUIRE_JWT_LIFETIME_DOCUMENTATION.examples[1].files[0].source,
    "import { jwtVerify } from 'jose'; const verify = (token, key) => jwtVerify(token, key, { maxTokenAge: 0 });",
    "import { jwtVerify } from 'jose'; const verify = (token, key) => jwtVerify(token, key, { maxTokenAge: -1 });",
    "import { jwtVerify } from 'jose'; const verify = (token, key) => jwtVerify(token, key, { maxTokenAge: '1h' });",
    "import { jwtVerify } from 'jose'; function verify(token, key, options) { return jwtVerify(token, key, options); }",
    "import { jwtVerify } from 'jose'; function verify(token, key, options) { return jwtVerify(token, key, { ...options }); }",
    "import { jwtVerify } from './custom.js'; const verify = (token, key) => jwtVerify(token, key);",
    "import { jwtVerify } from 'jose'; function check(jwtVerify) { return jwtVerify(token, key); }",
    "import { jwtVerify } from 'jose'; async function check(token, key) { const result = await jwtVerify(token, key); assertExpiration(result); return result; }",
  ],
  invalid: [
    REQUIRE_JWT_LIFETIME_DOCUMENTATION.examples[0].files[0].source,
    "import { jwtVerify } from 'jose'; const verify = (token, key) => jwtVerify(token, key, { requiredClaims: ['iss'] });",
    "import { jwtVerify as verify } from 'jose'; const load = async (token, key) => await verify(token, key, { issuer: 'app' });",
    "import * as jose from 'jose'; const verify = (token, key) => jose.jwtVerify(token, key, {});",
  ].map(code => ({ code, errors: [{ messageId: "lifetime" as const }] })),
});
