/** @fileoverview prefer-discriminated-union — the documentation and executable examples of `@sarj/prefer-discriminated-union`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_DISCRIMINATED_UNION_DOCUMENTATION = {
  summary: "Prefer discriminated unions for result contracts and locally proven tag-specific return payloads.",
  defaultLevel: "warning",
  rationale: "A flat object with optional branch data loses the relationship between a tag and its payload. Callers cannot narrow to the required fields, and the type permits incomplete or contradictory combinations.",
  remediation: "If the variants are mutually exclusive, represent each with a literal tag and its required payload. Preserve shared fields on every member, including payload value types and nullability. For a producer returning a subset of a broader wire contract, give the producer a precise domain return type after validation.",
  category: "correctness",
  autofix: "safe",
  limitations: [
    "The legacy boolean-result advisory recognizes local status and payload names; those names do not prove that partial-success outcomes are forbidden. Review the domain before changing its representation.",
    "Producer analysis requires a finite literal tag, every declared tag syntactically witnessed, exhaustive simple return paths without literal constant conditions, plain object returns, and consistent optional-field presence for each tag. It resolves only unmerged local aliases/interfaces without inheritance or generics, and the built-in Promise around async returns. This is syntax-only evidence of field presence; explicit undefined, void and null payloads are skipped, while expression value types are not inferred. Dynamic returns, spreads, computed keys, accessors, loops and try statements are deliberately skipped.",
    "A switch producer is supported only for a non-overloaded function declaration when its sole body statement switches on an unchanged direct string or number parameter, has unique same-kind literal labels and a default, and every nonempty case body is a sole object return or throw, optionally inside sole blocks. Empty labels may share the next terminating body; nested conditions, conditional returns, statement prefixes, breaks, other fallthrough, captured/closed inputs and switches under preceding control flow abstain. Broad parameter domains establish input witnesses for each label and the default; this does not infer branch-specific runtime effects or expression value types. Path visits, depth and returned objects are bounded conservatively.",
    "Returned variants prove this producer's key relationships, not all legal consumers of a shared type. Automatic fixes are limited to an unused private nongeneric synchronous function with a direct inline contract and one literal-object conditional return; they preserve original member types and all runtime code. Shared/observed contracts and generated/declaration/test files remain excluded.",
  ],
  references: ["https://functional-architecture.org/make_illegal_states_unrepresentable/", "https://www.typescriptlang.org/docs/handbook/2/narrowing.html#discriminated-unions"],
  examples: [
    { id: "explicit-result-branches", title: "Use explicit result branches", outcome: "no-match", files: [{ path: "src/result.ts", source: "type Result = { ok: true; data: string } | { ok: false; error: string };" }], focusPath: "src/result.ts", expectedCount: 0, public: true },
    { id: "optional-result-payloads", title: "Review optional result payloads", outcome: "match", files: [{ path: "src/result.ts", source: "type Result = { ok: boolean; data?: string; error?: string };" }], focusPath: "src/result.ts", expectedCount: 1, public: true },
    { id: "flat-produced-variants", scenarioId: "produced-variants", title: "Preserve producer variant relationships", outcome: "match", files: [{ path: "src/job.ts", source: 'function job(done: boolean): { phase: "queued" | "complete"; ticket?: string } { return done ? { phase: "complete" } : { phase: "queued", ticket: "t" }; }' }], focusPath: "src/job.ts", expectedCount: 1, public: true },
    { id: "explicit-produced-variants", scenarioId: "produced-variants", title: "Give each produced variant its payload", outcome: "no-match", files: [{ path: "src/job.ts", source: 'function job(done: boolean): { phase: "queued"; ticket: string } | { phase: "complete" } { return done ? { phase: "complete" } : { phase: "queued", ticket: "t" }; }' }], focusPath: "src/job.ts", expectedCount: 0, public: true },
    { id: "flat-switch-producer", scenarioId: "switch-producer", title: "A complete dispatcher preserves each returned variant", outcome: "match", files: [{ path: "src/job.ts", source: 'function job(command: string): { phase: "queued" | "complete"; ticket?: string } { switch (command) { case "start": return { phase: "queued", ticket: "t" }; default: return { phase: "complete" }; } }' }], focusPath: "src/job.ts", expectedCount: 1, public: true },
    { id: "explicit-switch-variants", scenarioId: "switch-producer", title: "An explicit dispatcher result supports payload narrowing", outcome: "no-match", files: [{ path: "src/job.ts", source: 'function job(command: string): { phase: "queued"; ticket: string } | { phase: "complete" } { switch (command) { case "start": return { phase: "queued", ticket: "t" }; default: return { phase: "complete" }; } }' }], focusPath: "src/job.ts", expectedCount: 0, public: true },
    {
      id: "safe-autofix",
      title: "Preserve an unused private producer's exact existing variants",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; function job(done: boolean): { phase: \"queued\" | \"complete\"; ticket?: string } { return done ? { phase: \"complete\" } : { phase: \"queued\", ticket: \"t\" }; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; function job(done: boolean): { phase: \"complete\" } | { phase: \"queued\"; ticket: string } { return done ? { phase: \"complete\" } : { phase: \"queued\", ticket: \"t\" }; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
