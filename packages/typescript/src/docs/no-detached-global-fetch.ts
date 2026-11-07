/** @fileoverview no-detached-global-fetch — the documentation and executable examples of `@sarj/no-detached-global-fetch`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_DETACHED_GLOBAL_FETCH_DOCUMENTATION = {
  summary:
    "Keep the ambient global fetch receiver-safe when storing or explicitly rebinding it.",
  rationale:
    "Calling a raw ambient fetch through a class or object property supplies that object as `this`; receiver-sensitive hosts can reject that invocation only after deployment.",
  remediation:
    "Store a forwarding wrapper such as `(input, init) => fetch(input, init)`, or bind the callable to a compatible global or undefined receiver before storing it.",
  category: "correctness",
  autofix: "safe",
  references: [
    "https://webidl.spec.whatwg.org/#es-operations",
    "https://fetch.spec.whatwg.org/#fetch-method",
  ],
  limitations: [
    "The rule follows stable local variables and defaulted parameters from an unshadowed ambient fetch or globalThis/self/window fetch into direct class, object, or member storage.",
    "Bare local aliases, callback arguments, returns, direct calls, compatible global or undefined bind/call/apply receivers, tests, scripts, generated files, and locally defined fetch implementations are excluded.",
    "Interprocedural aliases, mutable aliases, collection storage, and host identity remain manual review boundaries.",
    "Automatic edits only bind a direct canonical ambient fetch to unshadowed undefined in a sole exported zero-argument ordinary function containing a private one-property object and its sole returned literal data-URL request. The callable and object never escape. Web IDL operations use the function realm's global object for an undefined receiver. Imports, comments, wrappers, other statements, options, shadows and identity observations remain manual; this repairs receiver behavior rather than preserving a host IllegalInvocation failure.",
  ],
  examples: [
    {
      id: "forwarded-global-fetch",
      title: "Store a receiver-safe forwarding wrapper",
      outcome: "no-match",
      files: [
        {
          path: "src/client.ts",
          source:
            "class Client { readonly request = (input: RequestInfo | URL, init?: RequestInit) => fetch(input, init); }",
        },
      ],
      focusPath: "src/client.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "receiver-unsafe-global-fetch",
      title: "Do not store raw ambient fetch as an object method",
      outcome: "match",
      files: [
        {
          path: "src/client.ts",
          source: "class Client { readonly request = fetch; }",
        },
      ],
      focusPath: "src/client.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Bind the exclusively called private fetch to its realm receiver",
      outcome: "match",
      files: [
        {
          path: "src/client.ts",
          source:
            "export function load() { const client = { request: fetch }; return client.request('data:text/plain,hello'); }",
        },
      ],
      fixedFiles: [
        {
          path: "src/client.ts",
          source:
            "export function load() { const client = { request: fetch.bind(undefined) }; return client.request('data:text/plain,hello'); }",
        },
      ],
      focusPath: "src/client.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
