/** @fileoverview no-explicit-type-predicate — the documentation and executable examples of `@sarj/no-explicit-type-predicate`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_EXPLICIT_TYPE_PREDICATE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Use compiler-checked narrowing instead of handwritten type predicates.",
  rationale: "TypeScript trusts an explicit value is Type annotation without proving that its implementation recognizes that type in both branches. A stale or partial predicate can make callers read properties that do not exist. Direct discriminator checks and inferred predicates keep narrowing tied to the implementation.",
  remediation: "For owned variants, check the discriminated union's tag directly or let TypeScript infer a simple discriminator helper or null filter. Parse unknown external data with a specific schema and consume its validated value or discriminated result. Do not replace a predicate with a cast or a schema boolean wrapper that repeats the same unchecked type claim. If a native API cannot express the required static contract, isolate that boundary and use an exact-rule local suppression explaining the constraint.",
  category: "maintainability",
  autofix: "none",
  requiresTypeInformation: false,
  limitations: [
    "This is an explicit design policy, including otherwise correct handwritten predicates. Reports every authored TypeScript is predicate, including asserts value is Type, method and callback annotations, function types, overloads, ambient signatures and predicates inside casts or satisfies expressions.",
    "Direct discriminator checks, compiler-inferred predicates, ordinary boolean returns and plain asserts condition remain valid. A tag on unknown input does not validate its payload. Imported library guard calls and imported predicate types are not redeclarations and are not inspected.",
    "Shared generated, vendored and declaration-file exclusions apply. Maintained test implementations remain checked; strings, comments and JSDoc text are not TypeScript predicate nodes. There is no exemption based on helper names, imports or body shape.",
    "No automatic fix or suggestion removes an annotation: public and callback contracts, overloads, both narrowing branches, emitted declarations and existing TypeScript versions may depend on it. Review callers and preserve intentional runtime behavior when migrating. Existing partial and contradictory predicate rules retain their separate correctness checks.",
  ],
  references: [
    "https://www.typescriptlang.org/docs/handbook/2/narrowing.html#discriminated-unions",
    "https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-5.html#inferred-type-predicates",
    "https://zod.dev/basics",
  ],
  examples: [
    { id: "manual-predicate", title: "Avoid an unchecked narrowing annotation", outcome: "match", files: [{ path: "src/job.ts", source: "type Job = { kind: 'queued'; queue: string } | { kind: 'done'; result: string }; type Done = Extract<Job, {kind: 'done'}>; function isDone(job: Job): job is Done { return job.kind === 'done'; } function render(job: Job) { return isDone(job) ? job.result : job.queue; }" }], focusPath: "src/job.ts", expectedCount: 1, public: true },
    { id: "direct-discriminator", title: "Let the compiler narrow the tagged union", outcome: "no-match", files: [{ path: "src/job.ts", source: "type Job = { kind: 'queued'; queue: string } | { kind: 'done'; result: string }; function render(job: Job) { return job.kind === 'done' ? job.result : job.queue; }" }], focusPath: "src/job.ts", expectedCount: 0, public: true },
    { id: "inferred-predicate", scenarioId: "inference", title: "Infer a discriminator helper from its body", outcome: "no-match", files: [{ path: "src/job.ts", source: "type Job = { kind: 'queued'; queue: string } | { kind: 'done'; result: string }; const isDone = (job: Job) => job.kind === 'done';" }], focusPath: "src/job.ts", expectedCount: 0, public: true },
    { id: "written-predicate", scenarioId: "inference", title: "A written predicate remains an unchecked promise", outcome: "match", files: [{ path: "src/job.ts", source: "type Job = { kind: 'queued'; queue: string } | { kind: 'done'; result: string }; type Done = Extract<Job, {kind: 'done'}>; const isDone = (job: Job): job is Done => job.kind === 'done';" }], focusPath: "src/job.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
