/** @fileoverview prefer-node-crypto-hash — the documentation and executable examples of `@sarj/prefer-node-crypto-hash`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_NODE_CRYPTO_HASH_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Prefer the modern one-shot node:crypto hash API when streaming state is unnecessary.",
  rationale: "A createHash-update-digest chain allocates mutable streaming state for a single in-memory value; Node's built-in hash function expresses the one-shot operation directly and can use its optimized fast path.",
  remediation: "On a supported Node runtime, consider hash(algorithm, value, encoding). Preserve the output encoding explicitly: digest() returns a Buffer, while hash defaults to hex. Keep createHash for streams or multiple updates.",
  category: "performance",
  autofix: "safe",
  limitations: [
    "Only direct imports, const bindings, and inline calls with statically proven provenance from crypto or node:crypto are analyzed; arbitrary assignments and dynamic module specifiers are excluded.",
    "Only a literal algorithm with exactly one update call is reported; streaming and incremental hashes remain valid.",
    "Namespace bindings must remain read-only: visible writes, aliases, exports, inherited mutation or alias methods, unknown computed members, and other escaping uses are excluded; type-only references and direct member calls remain eligible.",
    "CommonJS loads and default imports share one mutable native module object. A visible unsafe use of that object excludes its other loads; ESM named exports remain separate unless visible native export synchronization can update them.",
    "Automatic fixes require both existing canonical named node:crypto value imports, an already-read stable hash alias, a retained runtime createHash call outside every reportable one-shot chain, literal sha256/string/hex arguments, no shadowing/comments/optional chains, and no other value/side-effect imports, module augmentations, mock/loader APIs, test/story/support ownership or visible crypto/prototype/reflection authority changes.",
    "Runtime support, missing imports, receiver-binding changes, other encodings or algorithms, and streaming data remain manual. The automatic subset reuses existing named imports and never inserts new ones; no guaranteed speedup is promised.",
  ],
  references: ["https://nodejs.org/api/crypto.html#cryptohashalgorithm-data-options"],
  examples: [
    { id: "one-shot-hash", title: "Use Node's one-shot hash API", outcome: "no-match", files: [{ path: "case.ts", source: "import { hash } from 'node:crypto'; export const digest = hash('sha256', 'value', 'hex');" }], focusPath: "case.ts", expectedCount: 0, public: true },
    { id: "mutable-one-shot-chain", title: "Avoid mutable state for one value", outcome: "match", files: [{ path: "case.ts", source: "import { createHash } from 'node:crypto'; export const digest = createHash('sha256').update('value').digest('hex');" }], focusPath: "case.ts", expectedCount: 1, public: true },
    { id: "native-namespace", scenarioId: "stable-native-namespace", title: "An unchanged namespace retains native provenance", outcome: "match", files: [{ path: "case.ts", source: "const crypto = require('node:crypto'); export const digest = crypto.createHash('sha256').update('value').digest('hex');" }], focusPath: "case.ts", expectedCount: 1, public: true },
    { id: "replaced-namespace-member", scenarioId: "stable-native-namespace", title: "A replaced member has a different contract", outcome: "no-match", files: [{ path: "case.ts", source: "const crypto = require('node:crypto'); crypto.createHash = () => ({ update() { return this; }, digest() { return 'custom'; } }); export const digest = crypto.createHash('sha256').update('value').digest('hex');" }], focusPath: "case.ts", expectedCount: 0, public: true },
    {
      id: "safe-autofix",
      title: "Use an already available one-shot hash for literal UTF-8 input",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "import { createHash, hash } from \"node:crypto\"; export const existing = hash(\"sha256\", \"seed\", \"hex\"); export const streaming = createHash(\"sha256\"); export const digest = createHash(\"sha256\").update(\"value\").digest(\"hex\");" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "import { createHash, hash } from \"node:crypto\"; export const existing = hash(\"sha256\", \"seed\", \"hex\"); export const streaming = createHash(\"sha256\"); export const digest = hash(\"sha256\", \"value\", \"hex\");" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
