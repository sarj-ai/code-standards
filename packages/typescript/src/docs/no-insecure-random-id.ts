/** @fileoverview no-insecure-random-id — the documentation and executable examples of `@sarj/no-insecure-random-id`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_INSECURE_RANDOM_ID_DOCUMENTATION = {
  summary:
    "Disallow using `Math.random()` to generate identifiers, tokens, or secrets; use `crypto.randomUUID()` or `crypto.getRandomValues(...)` instead.",
  rationale:
    "Math.random is predictable and lacks the entropy required for security-sensitive values.",
  remediation:
    "Generate the value with crypto.randomUUID or crypto.getRandomValues.",
  category: "security",
  autofix: "safe",
  limitations: [
    "Names select security-sensitive bindings heuristically; they do not prove sensitivity. Sampling in unrelated bindings or branch tests, locally shadowed Math objects, ambiguous identifiers and test files are excluded. This is not interprocedural data-flow analysis. Automatic fixes cover only an exact RFC v4 x/y recipe in a closed module with explicit string APIs and an already-used bound crypto.randomUUID provider. Canonical unmodified Web Crypto, Math, String, RegExp, Number and Function.bind are assumed; the entropy upgrade intentionally changes random traces. Other recipes and providers remain manual.",
  ],
  examples: [
    {
      id: "cryptographic-id",
      title: "Use the Web Crypto API",
      outcome: "no-match",
      files: [
        {
          path: "src/session.ts",
          source: "const sessionToken = crypto.randomUUID();",
        },
      ],
      focusPath: "src/session.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "predictable-token",
      title: "Do not derive a token from Math.random",
      outcome: "match",
      files: [
        {
          path: "src/session.ts",
          source: "const sessionToken = Math.random();",
        },
      ],
      focusPath: "src/session.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "existing-native-provider",
      title: "Use the existing provider for the exact v4 recipe",
      outcome: "match",
      files: [
        {
          path: "src/ids.ts",
          source:
            "const nativeUuid = crypto.randomUUID.bind(crypto); function nativeId(): string { return nativeUuid(); } function recipeId(): string { return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const uuidDigit = Math.random() * 16 | 0; return (c === 'x' ? uuidDigit : (uuidDigit & 3) | 8).toString(16); }); } export function ids(): string[] { return [nativeId(), recipeId()]; }",
        },
      ],
      focusPath: "src/ids.ts",
      expectedCount: 1,
      fixedFiles: [
        {
          path: "src/ids.ts",
          source:
            "const nativeUuid = crypto.randomUUID.bind(crypto); function nativeId(): string { return nativeUuid(); } function recipeId(): string { return nativeUuid(); } export function ids(): string[] { return [nativeId(), recipeId()]; }",
        },
      ],
      public: false,
    },
  ],
} as const satisfies RuleDocumentation;
