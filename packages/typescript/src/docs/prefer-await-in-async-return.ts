/** @fileoverview prefer-await-in-async-return — the documentation and executable examples of `@sarj/prefer-await-in-async-return`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_AWAIT_IN_ASYNC_RETURN_DOCUMENTATION = {
  summary:
    "Prefer explicit `await` for proven Promise `.then` calls; the default scope checks direct async returns.",
  rationale:
    "Promise callback chains mix explicit async control flow with nested callbacks, making sequencing and failure handling harder to read.",
  remediation:
    "Consider awaiting the Promise and returning the transformed value with ordinary async statements. Preserve catch boundaries, callback behavior, and observable scheduling when rewriting manually.",
  category: "maintainability",
  since: "15.6.3",
  limitations: [
    "The default async-return scope checks one directly returned `.then` call with an inline callback. The all-promise-calls scope checks direct calls to built-in Promise/PromiseLike.then, including optional and literal-computed calls, without automatic rewrites.",
    "The receiver must be proven Promise-like by TypeScript; an earlier chain can still produce that receiver. The default async-return scope excludes rejection handlers and named callbacks. This is not the upstream return-await policy and no scheduling equivalence is promised.",
    "The default async-return scope excludes direct loader callbacks passed to resolved `React.lazy` and `next/dynamic` imports because returning the module Promise is their framework contract.",
    "All-promise-calls requires type information and excludes unproven/custom thenables, dynamic property names, property reads, destructuring, and extracted method aliases. Catch and finally remain available. Framework callback exclusions apply only to the default async-return scope.",
  ],
  examples: [
    {
      id: "explicit-async-transform",
      title: "Use explicit async control flow",
      outcome: "no-match",
      files: [{
        path: "src/load.ts",
        source:
          "async function load() { const value = await Promise.resolve(1); return value + 1; }",
      }],
      focusPath: "src/load.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "returned-then-transform",
      title: "Do not directly return a Promise callback chain from async code",
      outcome: "match",
      files: [{
        path: "src/load.ts",
        source:
          "async function load() { return Promise.resolve(1).then((value) => value + 1); }",
      }],
      focusPath: "src/load.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
