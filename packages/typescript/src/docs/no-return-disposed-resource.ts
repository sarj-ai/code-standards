/** @fileoverview no-return-disposed-resource — the documentation and executable examples of `@sarj/no-return-disposed-resource`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_RETURN_DISPOSED_RESOURCE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Do not return a resource whose using declaration disposes it before the caller receives it.",
  rationale: "Leaving the resource's using scope invokes its disposer before the returned value reaches its consumer, producing an already disposed dependency.",
  remediation: "Keep consumers inside the resource scope, yield it through an awaited fixture use callback, or transfer ownership without a using declaration. Return an independent snapshot when appropriate.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Reports directly returned bindings declared with using or await using in the same function, including unchanged const aliases. Explicit resource-management syntax proves disposal; method names such as close or destroy are not guessed.",
    "Nested closures retaining an outer resource, returned object aggregates, dynamic wrappers, mutable aliases and deliberate disposed-resource contracts are not inferred. Awaited fixture use callbacks and snapshots remain valid.",
    "Findings remain warnings because an intentional disposed-resource contract requires review. No automatic ownership or cleanup rewrite is offered.",
  ],
  examples: [
    { id: "return-disposed-client", title: "The resource is disposed before return", outcome: "match", files: [{ path: "src/client.ts", source: "function client() { using handle = acquire(); return handle; }" }], focusPath: "src/client.ts", expectedCount: 1, public: true },
    { id: "return-snapshot", title: "Return a value independent of resource lifetime", outcome: "no-match", files: [{ path: "src/client.ts", source: "function client() { using handle = acquire(); return handle.snapshot(); }" }], focusPath: "src/client.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
