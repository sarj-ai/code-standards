/** @fileoverview prefer-constant-time-secret-compare — the documentation and executable examples of `@sarj/prefer-constant-time-secret-compare`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_CONSTANT_TIME_SECRET_COMPARE_DOCUMENTATION = {
  summary: "Prefer a supported constant-time comparison primitive for secret-like values.",
  rationale: "Ordinary equality offers no constant-time guarantee for comparing secrets.",
  remediation: "Compare equal-length cryptographic digests with a constant-time comparison primitive.",
  category: "security",
  limitations: ["This uses secret-name heuristics and bounded stable local aliases of credential headers from an unshadowed native Request or imported NextRequest. Literal header names include no-substitution templates and erased TypeScript wrappers; unknown receivers and mutated aliases are excluded. This is not proof of runtime sensitivity. Ambiguous token names require an authentication or cryptographic qualifier; test files and public sentinel comparisons are excluded."],
  examples: [
    { id: "constant-time-compare", title: "Use a constant-time comparison", outcome: "no-match", files: [{ path: "src/auth.ts", source: "if (await constantTimeEqual(presentedAccessToken, expectedAccessToken)) { allow(); }" }], focusPath: "src/auth.ts", expectedCount: 0, public: true },
    { id: "secret-equality", title: "Do not compare authentication tokens with equality", outcome: "match", files: [{ path: "src/auth.ts", source: "if (presentedAccessToken === expectedAccessToken) { allow(); }" }], focusPath: "src/auth.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
