/** @fileoverview no-contradictory-overload-return — the documentation and executable examples of `@sarj/no-contradictory-overload-return`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_CONTRADICTORY_OVERLOAD_RETURN_DOCUMENTATION = {
  summary: "Preserve the input/result relationship promised by literal overloads.",
  rationale: "TypeScript checks an overload implementation against an overall envelope, without proving each input/result relationship. A function can compile while returning the opposite domain variant for every advertised literal input.",
  remediation: "Return the variant promised for each input. Prefer a checked case map or separate variant-specific operations when that makes the relationship explicit; retain overloads required by public APIs.",
  category: "correctness", defaultLevel: "error", autofix: "safe",
  limitations: [
    "Automatic fixes align only an unused private complete same-file overload group with its existing literal implementation results. Binding aliases, exports, merges, eval, declaration files, comments, nonliteral result syntax and observed callers preserve manual ownership; runtime checks and returned values never change.",
    "Requires type information and a top-level non-generic, synchronous function with two to 32 unique, single-required-parameter overloads. Each public input must be a directly authored string, finite number, boolean or null literal. Broad, duplicate, aliased, optional, rest and multi-parameter inputs are excluded.",
    "The implementation must have one required identifier parameter and only return a strict literal equality/inequality conditional. Both branches must be primitive literals or flat objects containing only primitive literal property assignments. Calls, computed keys, getters, spreads, duplicate keys and __proto__ are excluded.",
    "Reports only a concrete returned literal incompatible with its primitive contract or an explicit returned property incompatible with the corresponding primitive property contract. Missing properties, arbitrary structural incompatibility, brands, enums, opaque types, effects and general control flow are outside this proof.",
    "Compiler-invalid implementation input/output envelopes, generated files, ambient declarations, methods and callbacks are excluded. Null input overloads require strictNullChecks: under loose null checking an earlier overload can mask their advertised result. No automatic rewrite changes a public overload or its runtime behavior.",
  ],
  references: ["https://www.typescriptlang.org/docs/handbook/2/functions.html#overload-signatures-and-the-implementation-signature"],
  examples: [
    { id: "correct-case-results", title: "Match each literal input with its result", outcome: "no-match", files: [{ path: "src/load.ts", source: 'function load(kind: "text"): {kind: "text"};\nfunction load(kind: "count"): {kind: "count"};\nfunction load(kind: "text" | "count"): {kind: "text" | "count"} { return kind === "text" ? {kind: "text"} : {kind: "count"}; }' }], focusPath: "src/load.ts", expectedCount: 0, public: true },
    { id: "inverted-case-results", title: "Do not swap domain variants behind overloads", outcome: "match", files: [{ path: "src/load.ts", source: 'function load(kind: "text"): {kind: "text"};\nfunction load(kind: "count"): {kind: "count"};\nfunction load(kind: "text" | "count"): {kind: "text" | "count"} { return kind === "text" ? {kind: "count"} : {kind: "text"}; }' }], focusPath: "src/load.ts", expectedCount: 2, public: true },
    {
      id: "safe-autofix",
      title: "Align an unused private overload group with its literal results",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; function choose(value: \"a\"): \"left\"; function choose(value: \"b\"): \"right\"; function choose(value: \"a\" | \"b\"): \"left\" | \"right\" { return value === \"a\" ? \"right\" : \"left\"; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; function choose(value: \"a\"): \"right\"; function choose(value: \"b\"): \"left\"; function choose(value: \"a\" | \"b\"): \"left\" | \"right\" { return value === \"a\" ? \"right\" : \"left\"; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 2,
    },
    {
      id: "safe-autofix-record",
      title: "Align an unused private overload group with its flat literal result",
      outcome: "match",
      files: [{ path: "src/autofix-record.ts", source: "export {}; function load(kind: \"text\"): {kind: \"text\"}; function load(kind: \"count\"): {kind: \"count\"}; function load(kind: \"text\" | \"count\"): {kind: \"text\" | \"count\"} { return kind === \"text\" ? {kind: \"count\"} : {kind: \"text\"}; }" }],
      fixedFiles: [{ path: "src/autofix-record.ts", source: "export {}; function load(kind: \"text\"): { \"kind\": \"count\" }; function load(kind: \"count\"): { \"kind\": \"text\" }; function load(kind: \"text\" | \"count\"): {kind: \"text\" | \"count\"} { return kind === \"text\" ? {kind: \"count\"} : {kind: \"text\"}; }" }],
      focusPath: "src/autofix-record.ts",
      expectedCount: 2,
    },
  ],
} as const satisfies RuleDocumentation;
