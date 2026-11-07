// vitest: shared-module-graph
import rule from "../../src/rules/require-jwt-lifetime.js";
import { ruleTester } from "./_tester.js";

const REQUIRE_JWT_LIFETIME_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Require an expiration claim or a maximum token age when returning a verified JWT.",
  rationale: "JOSE validates exp when present but does not require it by default, so otherwise valid tokens without an expiration may remain accepted indefinitely.",
  remediation: "Set requiredClaims: ['exp'] or a finite maxTokenAge in jwtVerify options. Keep issuer and audience checks appropriate to the protocol.",
  category: "security",
  references: ["https://github.com/panva/jose/blob/main/docs/jwt/verify/interfaces/JWTVerifyOptions.md"],
  limitations: [
    "Checks direct return or concise-arrow-return calls, including await, to runtime ESM-import-proven jose jwtVerify with absent options or a literal options object lacking both lifetime controls. Aliased imports and namespace imports are resolved lexically.",
    "Opaque options, spreads, local claim validation before return, custom verifiers, generated files and tests are excluded. Existing native jose validation is assumed. No automatic protocol policy is invented.",
  ],
  examples: [
    { id: "optional-expiration", title: "A signature alone does not require expiration", outcome: "match", files: [{ path: "auth.ts", source: "import { jwtVerify } from 'jose'; function verify(token, key) { return jwtVerify(token, key); }" }], focusPath: "auth.ts", expectedCount: 1, public: true },
    { id: "required-expiration", title: "Require the expiration claim", outcome: "no-match", files: [{ path: "auth.ts", source: "import { jwtVerify } from 'jose'; function verify(token, key) { return jwtVerify(token, key, { requiredClaims: ['exp'] }); }" }], focusPath: "auth.ts", expectedCount: 0, public: true },
  ],
} as const;
const TESTER = ruleTester();
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
