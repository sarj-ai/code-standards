/** @fileoverview prefer-schema-for-api-payload — the documentation and executable examples of `@sarj/prefer-schema-for-api-payload`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_SCHEMA_FOR_API_PAYLOAD_DOCUMENTATION = {
  summary: "Require Zod (or similar) schema validation on `response.json()` / `JSON.parse()` results before property access.",
  rationale: "External JSON is untrusted at runtime even when its expected TypeScript shape is known statically.",
  remediation: "For external payloads, parse through a schema or establish runtime validation before reading fields. Review validator implementations separately rather than recursively requiring another schema.",
  category: "correctness",
  limitations: [
    "A JSON.parse call alone does not prove external input; exact native JSON stringify/parse round trips are excluded. Validator implementations and other non-network parsing can still require manual review rather than a schema rewrite.",
    "JSON.parse must resolve to the global JSON object. json() receivers require an unshadowed global Request/Response annotation or construction, or stable local aliases of global fetch results, including native global members and bounded stable const fetch aliases or destructuring; imported, inferred and unknown response types are deliberately not inferred.",
    "Named validators remain conventions, not proof of their implementation. Their exemptions are confined to a valid branch or a preceding same-block validation statement; ignored predicate results and deferred callbacks do not validate later reads.",
    "Test fixtures, generated clients and recognized local-file reads are excluded. This is bounded local analysis, not a general control-flow or mutation proof.",
  ],
  examples: [
    { id: "validated-payload", title: "Validate before property access", outcome: "no-match", files: [{ path: "src/client.ts", source: "import { z } from 'zod';\nconst UserSchema = z.object({ id: z.string() });\nasync function load(response: Response) { const body = UserSchema.parse(await response.json()); return body.id; }" }], installedDependencies: [{ module: "zod", version: "4.6.7" }], focusPath: "src/client.ts", expectedCount: 0, public: true },
    { id: "unvalidated-payload", title: "Do not trust response JSON directly", outcome: "match", files: [{ path: "src/client.ts", source: "async function load(response: Response) { const body = await response.json(); return body.id; }" }], focusPath: "src/client.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
