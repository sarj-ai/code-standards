/** @fileoverview prefer-native-fetch-in-server-actions — the documentation and executable examples of `@sarj/prefer-native-fetch-in-server-actions`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_NATIVE_FETCH_IN_SERVER_ACTIONS_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Server action modules should call native fetch instead of importing ky.",
  rationale:
    "ky wraps request bodies and responses for browser runtimes; in Next.js server actions it has failed on binary uploads with `ArrayBuffer.slice` errors, and its errors copy the signed request URL into messages and metadata.",
  remediation:
    "Use the platform `fetch` with an explicit `signal: AbortSignal.timeout(...)` and check `response.ok` in the server action.",
  category: "correctness",
  limitations: [
    "Only modules whose directive prologue contains `use server` are checked.",
    "Type-only imports are allowed; ky reached through a shared client module is not followed.",
  ],
  examples: [
    {
      id: "native-fetch-action",
      title: "A server action uploads with native fetch",
      outcome: "no-match",
      files: [{
        path: "src/app/actions.ts",
        source:
          "\"use server\";\n\nexport async function upload(url: string, body: Blob): Promise<void> {\n" +
          "  const response = await fetch(url, { method: \"PUT\", body, signal: AbortSignal.timeout(30_000) });\n" +
          "  if (!response.ok) throw new Error(`upload failed: ${response.status}`);\n}\n",
      }],
      focusPath: "src/app/actions.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "ky-in-action",
      title: "A server action imports ky",
      outcome: "match",
      files: [{
        path: "src/app/actions.ts",
        source:
          "\"use server\";\n\nimport ky from \"ky\";\n\nexport async function upload(url: string, body: Blob): Promise<void> {\n" +
          "  await ky.put(url, { body });\n}\n",
      }],
      focusPath: "src/app/actions.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
