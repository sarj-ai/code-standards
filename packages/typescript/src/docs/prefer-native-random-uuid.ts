/** @fileoverview prefer-native-random-uuid — the documentation and executable examples of `@sarj/prefer-native-random-uuid`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_NATIVE_RANDOM_UUID_DOCUMENTATION = {
  summary:
    "Prefer `globalThis.crypto.randomUUID()` over resolved zero-argument UUID v4 bindings from the `uuid` package.",
  rationale:
    "The platform implementation avoids an unnecessary dependency for standard random UUID generation.",
  remediation:
    "Call `globalThis.crypto.randomUUID()` and remove the unused `uuid` v4 import when possible.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Only resolved zero-argument UUID v4 calls are reported; customized and other UUID versions are excluded. Automatic fixes require an exact closed UUID-only module, explicit string APIs, an already-used bound crypto.randomUUID provider, and another already-read NIL import that preserves uuid package evaluation. Canonical unmodified uuid, Web Crypto and Function.bind are assumed; entropy traces may intentionally differ. Other shapes retain suggestions requiring unshadowed globalThis and comment-free calls; verify native randomUUID availability in the deployment runtime.",
  ],
  examples: [
    {
      id: "native-random-uuid",
      title: "Use the platform UUID generator",
      outcome: "no-match",
      files: [
        {
          path: "src/id.ts",
          source: "const id = globalThis.crypto.randomUUID();",
        },
      ],
      focusPath: "src/id.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "uuid-v4-package",
      title: "Do not call uuid v4 without options",
      outcome: "match",
      files: [
        {
          path: "src/id.ts",
          source: "import { v4 } from 'uuid'; const id = v4();",
        },
      ],
      focusPath: "src/id.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "existing-native-provider",
      title: "Reuse the existing native UUID provider",
      outcome: "match",
      files: [
        {
          path: "src/ids.ts",
          source:
            "import { v4, NIL } from 'uuid'; const nativeUuid = crypto.randomUUID.bind(crypto); function nativeId(): string { return nativeUuid(); } function packageId(): string { return v4(); } export function ids(): string[] { return [nativeId(), packageId(), NIL]; }",
        },
      ],
      focusPath: "src/ids.ts",
      expectedCount: 1,
      expectedDiagnostics: [{
        messageId: "preferNative",
        message: "Where supported by the deployment runtime, prefer native `globalThis.crypto.randomUUID()` over the `uuid` package for UUID v4.",
        location: { line: 1, column: 175, end: { line: 1, column: 179 } },
        automaticFix: true,
        suggestions: [{
          messageId: "replaceWithNative",
          output: "import { v4, NIL } from 'uuid'; const nativeUuid = crypto.randomUUID.bind(crypto); function nativeId(): string { return nativeUuid(); } function packageId(): string { return globalThis.crypto.randomUUID(); } export function ids(): string[] { return [nativeId(), packageId(), NIL]; }",
        }],
      }],
      fixedFiles: [
        {
          path: "src/ids.ts",
          source:
            "import { NIL } from 'uuid'; const nativeUuid = crypto.randomUUID.bind(crypto); function nativeId(): string { return nativeUuid(); } function packageId(): string { return nativeUuid(); } export function ids(): string[] { return [nativeId(), packageId(), NIL]; }",
        },
      ],
      public: false,
    },
    {
      id: "uuid-v4-suggestion-only",
      title: "Keep the unproven native replacement as a suggestion",
      outcome: "match",
      files: [{ path: "src/id.ts", source: "import { v4 } from 'uuid'; const id = v4();" }],
      focusPath: "src/id.ts",
      expectedCount: 1,
      expectedDiagnostics: [{
        messageId: "preferNative",
        message: "Where supported by the deployment runtime, prefer native `globalThis.crypto.randomUUID()` over the `uuid` package for UUID v4.",
        location: { line: 1, column: 39, end: { line: 1, column: 43 } },
        automaticFix: false,
        suggestions: [{
          messageId: "replaceWithNative",
          output: "import { v4 } from 'uuid'; const id = globalThis.crypto.randomUUID();",
        }],
      }],
    },
  ],
} as const satisfies RuleDocumentation;
