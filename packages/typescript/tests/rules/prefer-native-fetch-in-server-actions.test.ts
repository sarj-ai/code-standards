// vitest: shared-module-graph
import rule from "../../src/rules/prefer-native-fetch-in-server-actions.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

RULE_TESTER.run("prefer-native-fetch-in-server-actions", rule, {
  valid: [
    {
      name: "documented example native-fetch-action",
      filename: "src/app/actions.ts",
      code:
        "\"use server\";\n\nexport async function upload(url: string, body: Blob): Promise<void> {\n" +
        "  const response = await fetch(url, { method: \"PUT\", body, signal: AbortSignal.timeout(30_000) });\n" +
        "  if (!response.ok) throw new Error(`upload failed: ${response.status}`);\n}\n",
    },
    "import ky from 'ky'; export const client = ky.create({});",
    "'use client'; import ky from 'ky';",
    "import ky from 'ky'; 'use server';",
    "'use server'; import type { HTTPError } from 'ky';",
    "'use server'; import { type Options } from 'ky';",
    "'use server'; import { kyLike } from 'ky-like';",
    "'use server'; export async function load(): Promise<Response> { return fetch('https://example.com'); }",
  ],
  invalid: [
    {
      name: "documented example ky-in-action",
      filename: "src/app/actions.ts",
      code:
        "\"use server\";\n\nimport ky from \"ky\";\n\nexport async function upload(url: string, body: Blob): Promise<void> {\n" +
        "  await ky.put(url, { body });\n}\n",
      errors: 1,
    },
    {
      code: "'use server'; import ky from 'ky';",
      errors: [{ messageId: "preferNativeFetchInServerActions" }],
    },
    {
      code: "'use strict'; \"use server\"; import { HTTPError } from 'ky';",
      errors: [{ messageId: "preferNativeFetchInServerActions" }],
    },
    {
      code: "'use server'; import ky from 'ky/distribution/index.js';",
      errors: [{ messageId: "preferNativeFetchInServerActions" }],
    },
  ],
});
