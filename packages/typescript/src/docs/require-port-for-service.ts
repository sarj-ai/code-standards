/** @fileoverview require-port-for-service — the documentation and executable examples of `@sarj/require-port-for-service`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_PORT_FOR_SERVICE_DOCUMENTATION = {
  summary:
    "Advise when an exported service with injected collaborators has public methods not covered by its declared ports.",
  rationale:
    "A declared port keeps consumers coupled to the service capability instead of its concrete implementation.",
  remediation:
    "Declare and implement an interface covering the service's public methods.",
  category: "architecture",
  autofix: "safe",
  aliases: ["require-interface-for-injected-service"],
  limitations: [
    "Automatic fixes only add the exact existing closed type alias named by an already-authored direct factory return annotation. A complete comment-free four-declaration module must contain one exported closed object type alias containing one zero-argument void method, one local matching worker interface, one ordinary nonabstract nongeneric class with an empty constructor retaining a private readonly worker parameter and one matching public forwarding method, and one exported ordinary required-worker-parameter factory returning that exact new class as the port. Unique lexical bindings, no heritage/decorators/defaults/imports/merges/other members or authority, and exact existing types/calls are required. Mergeable public interfaces are refused because downstream declaration augmentation can introduce a private-field compatibility error. No contract, method, field, import or name is invented; emitted JavaScript remains identical. Other shapes remain manual.",
    "Retained injection requires an untouched parameter property or a single direct, unconditional constructor assignment. Conditional, repeated, replaced, updated, or deleted stores are unresolved rather than proof of retained injection.",
  ],
  examples: [
    {
      id: "declared-service-port",
      title: "Implement the service port",
      outcome: "no-match",
      files: [
        {
          path: "src/service.ts",
          source:
            "interface Handler { handle(): void }\nexport class RequestHandler implements Handler { constructor(private readonly store: TaskStore) {} handle(): void { this.store.handle(); } }",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "concrete-injected-service",
      title: "Do not expose only the concrete service",
      outcome: "match",
      files: [
        {
          path: "src/service.ts",
          source:
            "export class RequestHandler { constructor(private readonly store: TaskStore) {} handle(): void { this.store.handle(); } }",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 1,
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
            "export type Port = { run(): void; };\ninterface Worker { run(): void; }\nexport class Service { constructor(private readonly worker: Worker) {} run(): void { this.worker.run(); } }\nexport function create(worker: Worker): Port { return new Service(worker); }",
        },
      ],
      fixedFiles: [
        {
          path: "src/service.ts",
          source:
            "export type Port = { run(): void; };\ninterface Worker { run(): void; }\nexport class Service implements Port { constructor(private readonly worker: Worker) {} run(): void { this.worker.run(); } }\nexport function create(worker: Worker): Port { return new Service(worker); }",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
