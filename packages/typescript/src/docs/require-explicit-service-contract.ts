/** @fileoverview require-explicit-service-contract — the documentation and executable examples of `@sarj/require-explicit-service-contract`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_EXPLICIT_SERVICE_CONTRACT_DOCUMENTATION = {
  defaultLevel: "error",
  summary:
    "Require explicit contracts for classes that invoke retained collaborators.",
  rationale:
    "A one-operation service can orchestrate a collaborator without declaring the contract that callers consume and implementations and fakes satisfy.",
  remediation:
    "Explicitly implement a focused interface or extend an abstract class covering the service operations. Export the contract only when its consumers need it.",
  category: "architecture",
  autofix: "safe",
  limitations: [
    "Automatic fixes only add the exact existing closed type alias named by an already-authored direct factory return annotation. A complete comment-free four-declaration module must contain one exported closed object type alias containing one zero-argument void method, one local matching worker interface, one ordinary nonabstract nongeneric class with an empty constructor retaining a private readonly worker parameter and one matching public forwarding method, and one exported ordinary required-worker-parameter factory returning that exact new class as the port. Unique lexical bindings, no heritage/decorators/defaults/imports/merges/other members or authority, and exact existing types/calls are required. Mergeable public interfaces are refused because downstream declaration augmentation can introduce a private-field compatibility error. No contract, method, field, import or name is invented; emitted JavaScript remains identical. Other shapes remain manual.",
    "The rule checks service, store, and provider class declarations whose constructor stores a typed behavioral collaborator and whose public method reaches that collaborator.",
    "Existing local interfaces, type aliases, and inherited contracts can cover the operations; the compiler owns signature compatibility.",
    "Imported or dynamic base classes with unavailable declarations and decorated classes or operations are unresolved and do not produce a finding.",
    "Constructor retention requires an untouched parameter property or one direct, unconditional assignment. Written or replaced operation members do not prove their declared bodies execute; external aliases, mutators, and callbacks are not resolved.",
    "Generated files and JavaScript without implements syntax are excluded.",
  ],
  examples: [
    {
      id: "single-operation-service-without-contract",
      title: "A single service operation still needs its contract",
      outcome: "match",
      files: [
        {
          path: "src/service.ts",
          source:
            "class OrchestratorService { constructor(private readonly worker: Worker) {} run(): void { this.worker.run(); } }",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "explicit-single-operation-contract",
      title: "The service declares its operation",
      outcome: "no-match",
      files: [
        {
          path: "src/service.ts",
          source:
            "interface Runner { run(): void } class OrchestratorService implements Runner { constructor(private readonly worker: Worker) {} run(): void { this.worker.run(); } }",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "The existing factory already names the service contract",
      outcome: "match",
      files: [
        {
          path: "src/service.ts",
          source:
            "export type Port = { run(): void; };\ninterface Worker { run(): void; }\nclass Service { constructor(private readonly worker: Worker) {} run(): void { this.worker.run(); } }\nexport function create(worker: Worker): Port { return new Service(worker); }",
        },
      ],
      fixedFiles: [
        {
          path: "src/service.ts",
          source:
            "export type Port = { run(): void; };\ninterface Worker { run(): void; }\nclass Service implements Port { constructor(private readonly worker: Worker) {} run(): void { this.worker.run(); } }\nexport function create(worker: Worker): Port { return new Service(worker); }",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
