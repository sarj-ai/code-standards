/** @fileoverview require-fetch-timeout — the documentation and executable examples of `@sarj/require-fetch-timeout`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_FETCH_TIMEOUT_DOCUMENTATION = {
  summary:
    "Require an explicit abort signal on locally analyzable global fetch calls.",
  rationale:
    "An unbounded request can occupy work indefinitely when an upstream stalls.",
  remediation:
    "Pass an abort signal, such as `AbortSignal.timeout(ms)`, in the fetch init.",
  category: "correctness",
  limitations: [
    "Signal presence establishes an explicit cancellation path, not a guaranteed timeout. Literal null, global undefined, and void 0 do not provide a signal. Erased TypeScript wrappers preserve the same analysis. Unknown spreads and dynamic values are not inferred. Forwarded Request objects retain their signal unless an init explicitly resets it to null.",
    "Unshadowed native fetch members and bounded stable const aliases or destructuring are recognized. Reassigned, defaulted and unknown aliases and arbitrary forwarding functions are excluded.",
    "Visible writes, callable escapes, whole-global escapes and mutation capabilities anywhere in the file invalidate native fetch identity, including earlier captures. Known unrelated global member writes and typeof global checks do not. Static constructor members and destructuring projections invalidate the proof; indirect reflection and external monkeypatches are not inferred.",
    "Accessors and unproved prototypes are excluded because native option conversion can attach or replace a signal before it is read.",
  ],
  examples: [
    {
      id: "bounded-fetch",
      title: "Bound the request",
      outcome: "no-match",
      files: [
        {
          path: "src/client.ts",
          source: "await fetch(url, { signal: AbortSignal.timeout(5000) });",
        },
      ],
      focusPath: "src/client.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "unbounded-fetch",
      title: "Do not leave fetch unbounded",
      outcome: "match",
      files: [
        {
          path: "src/client.ts",
          source: "await fetch('https://api.example.com/items');",
        },
      ],
      focusPath: "src/client.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
