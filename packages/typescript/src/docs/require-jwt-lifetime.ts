/** @fileoverview require-jwt-lifetime — the documentation and executable examples of `@sarj/require-jwt-lifetime`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_JWT_LIFETIME_DOCUMENTATION = {
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
} as const satisfies RuleDocumentation;
