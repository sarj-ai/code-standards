/** @fileoverview require-explicit-contract-implementation — the documentation and executable examples of `@sarj/require-explicit-contract-implementation`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_EXPLICIT_CONTRACT_IMPLEMENTATION_DOCUMENTATION = {
  defaultLevel: "error",
  summary:
    "Require nominal inheritance when an injected abstract class is rejected by an instanceof guard.",
  rationale:
    "A structurally assignable fake can still fail a constructor's nominal runtime guard. Pure structural interfaces do not require an implements clause.",
  remediation:
    "Use an implementation inheriting the existing abstract class, or remove the nominal guard if the boundary is intentionally structural.",
  category: "architecture",
  autofix: "safe",
  limitations: [
    "Requires direct construction of both owned consumer and collaborator classes, with a first-statement consumer constructor guard rejecting the exact parameter with if (!(parameter instanceof Contract)) throw. Parentheses preserve exact constructor and guard symbol identity; casts remain excluded.",
    "The contract must resolve to an abstract class without decorators, static blocks, unresolved ancestors, or custom computed static members in its resolved hierarchy. Escaped class constructors are checked across every owned module in the typed program.",
    "Structural interfaces, non-rejecting branches, reassignment before the guard, casts, unresolved heritage, dynamic factories, implementation static blocks, explicit implementation constructors or initializers, involved modules referencing prototype-mutator members or assigning prototypes, escaped class constructors, and third-party classes are excluded.",
    "Automatic edits only add the existing abstract base to a closed explicit module with exactly three private classes and one direct construction. The base has only one abstract void method and no constructor, fields, heritage, decorators or static work; the implementation has the matching empty method. The consumer retains the exact readonly parameter and TypeError nominal rejection guard. No guard is weakened. Other runtime inheritance or initialization remains manual; this intentionally repairs the diagnosed startup TypeError.",
  ],
  examples: [
    {
      id: "runtime-nominal-guard-with-structural-fake",
      title:
        "A structurally compatible fake fails the constructor's runtime guard",
      outcome: "match",
      files: [
        {
          path: "src/service.ts",
          source:
            "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "runtime-nominal-guard-with-inherited-fake",
      title: "The fake satisfies the existing nominal runtime contract",
      outcome: "no-match",
      files: [
        {
          path: "src/service.ts",
          source:
            "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher extends Publisher { publish() {} } new Consumer(new FakePublisher());",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Honor the already authored inert nominal runtime contract",
      outcome: "match",
      files: [
        {
          path: "src/service.ts",
          source:
            "export {}; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());",
        },
      ],
      fixedFiles: [
        {
          path: "src/service.ts",
          source:
            "export {}; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher extends Publisher { publish() {} } new Consumer(new FakePublisher());",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
