/** @fileoverview require-port-for-service — the documentation and executable examples of `@sarj/require-port-for-service`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_PORT_FOR_SERVICE_DOCUMENTATION = {
  summary:
    "Require exported-class contracts and advise when an exported injected service's public methods are not covered by its declared ports.",
  rationale:
    "A declared port keeps consumers coupled to the service capability instead of its concrete implementation. An explicit contract names the intended public capability separately from implementation details. TypeScript already supports structural compatibility; this is an architecture policy, not a prerequisite for substitution.",
  remediation:
    "Declare and implement an interface covering the service's public methods; for exported concrete classes, declare a focused interface or inherit from an intentional base contract.",
  category: "architecture",
  autofix: "safe",
  aliases: ["require-interface-for-injected-service", "require-interface-for-exported-class"],
  limitations: [
    "Automatic fixes only add the exact existing closed type alias named by an already-authored direct factory return annotation. A complete comment-free four-declaration module must contain one exported closed object type alias containing one zero-argument void method, one local matching worker interface, one ordinary nonabstract nongeneric class with an empty constructor retaining a private readonly worker parameter and one matching public forwarding method, and one exported ordinary required-worker-parameter factory returning that exact new class as the port. Unique lexical bindings, no heritage/decorators/defaults/imports/merges/other members or authority, and exact existing types/calls are required. Mergeable public interfaces are refused because downstream declaration augmentation can introduce a private-field compatibility error. No contract, method, field, import or name is invented; emitted JavaScript remains identical. Other shapes remain manual.",
    "Retained injection requires an untouched parameter property or a single direct, unconditional constructor assignment. Conditional, repeated, replaced, updated, or deleted stores are unresolved rather than proof of retained injection.",
    "JavaScript files are excluded from the exported-class contract check only because implements is TypeScript syntax; imported framework base contracts still require manual policy review.",
    "An exported injected service may also receive require-port-for-service: the two diagnostics intentionally enforce distinct service-boundary and general exported-contract policy scopes.",
    "The rule checks module-level class declarations and direct class-expression values exported directly, through local export specifiers, or through a default identifier; re-exports and expressions wrapped in other calls require review.",
    "An extends clause satisfies the contract only when its target is a locally declared abstract class; imported base-class contracts require an explicit implements clause.",
    "Static factories and data-only classes without public instance methods are outside the contract requirement.",
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
      expectedCount: 2,
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
      expectedCount: 2,
    },
    {
      id: "implemented-store-contract",
      title: "Export behavior through a focused contract",
      outcome: "no-match",
      files: [
        {
          path: "src/artifact-store.ts",
          source:
            "export interface ArtifactStorage { read(id: string): Promise<Uint8Array>; } export class ArtifactStore implements ArtifactStorage { async read(id: string) { return new Uint8Array(); } }",
        },
      ],
      focusPath: "src/artifact-store.ts",
      expectedCount: 0,
    },
    {
      id: "concrete-only-store",
      title: "Do not export behavior only through a concrete class",
      outcome: "match",
      files: [
        {
          path: "src/artifact-store.ts",
          source:
            "export class ArtifactStore { async read(id: string) { return new Uint8Array(); } }",
        },
      ],
      focusPath: "src/artifact-store.ts",
      expectedCount: 1,
    },
    {
      id: "exported-class-safe-autofix",
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
      expectedCount: 2,
    },
  ],
} as const satisfies RuleDocumentation;
