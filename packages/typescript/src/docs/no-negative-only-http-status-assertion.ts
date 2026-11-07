/** @fileoverview no-negative-only-http-status-assertion — the documentation and executable examples of `@sarj/no-negative-only-http-status-assertion`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_NEGATIVE_ONLY_HTTP_STATUS_ASSERTION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Assert the intended HTTP status instead of only excluding a server error.",
  rationale: "A response can avoid status 500 while still fail with an unrelated 400, 401 or 404, so the test can pass without exercising the intended behavior.",
  remediation: "Assert the expected response status or a deliberately bounded success/error contract. Preserve negative assertions that supplement an exact assertion for the same response.",
  category: "testing",
  autofix: "none",
  limitations: [
    "Checks direct Vitest/Jest/Bun/Playwright expect assertions in recognized test callbacks on a const response obtained from native fetch, runtime-imported undici/node-fetch, or unshadowed new Response. Direct global Response parameter annotations and stable const response aliases are also resolved. A server-error exclusion or status below 500 needs an accompanying unconditional exact HTTP status assertion for the same binding.",
    "Dynamic clients, mutable response bindings, helper functions, nested callbacks, status constants and nonliteral expected statuses are excluded. No HTTP intent is inferred from a variable name alone.",
    "An exact expected status is never guessed or inserted automatically. Nonliteral and richer response oracles require review outside this narrow detector.",
  ],
  examples: [
    { id: "only-excludes-server-error", title: "A missing route can still pass this test", outcome: "match", files: [{ path: "src/api.test.ts", source: "import {test,expect} from 'vitest'; test('reads', async () => { const response = await fetch('/versions'); expect(response.status).not.toBe(500); });" }], focusPath: "src/api.test.ts", expectedCount: 1, public: true },
    { id: "expects-intended-status", title: "Assert the API's intended result", outcome: "no-match", files: [{ path: "src/api.test.ts", source: "import {test,expect} from 'vitest'; test('reads', async () => { const response = await fetch('/versions'); expect(response.status).toBe(200); });" }], focusPath: "src/api.test.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
