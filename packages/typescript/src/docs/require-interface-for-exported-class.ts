/** @fileoverview require-interface-for-exported-class — the documentation and executable examples of `@sarj/require-interface-for-exported-class`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION = {
  defaultLevel: "error",
  summary:
    "Require exported concrete classes with public behavior to declare a contract.",
  rationale:
    "An explicit contract names the intended public capability separately from implementation details. TypeScript already supports structural compatibility; this is an architecture policy, not a prerequisite for substitution.",
  remediation:
    "Declare a focused interface and add an implements clause, or inherit from an intentional base contract.",
  category: "architecture",
  autofix: "safe",
  limitations: [
    "Automatic fixes only add the exact existing closed type alias named by an already-authored direct factory return annotation. A complete comment-free four-declaration module must contain one exported closed object type alias containing one zero-argument void method, one local matching worker interface, one ordinary nonabstract nongeneric class with an empty constructor retaining a private readonly worker parameter and one matching public forwarding method, and one exported ordinary required-worker-parameter factory returning that exact new class as the port. Unique lexical bindings, no heritage/decorators/defaults/imports/merges/other members or authority, and exact existing types/calls are required. Mergeable public interfaces are refused because downstream declaration augmentation can introduce a private-field compatibility error. No contract, method, field, import or name is invented; emitted JavaScript remains identical. Other shapes remain manual.",
    "JavaScript files are excluded because implements is TypeScript syntax; imported framework base contracts still require manual policy review.",
    "An exported injected service may also receive require-port-for-service: the two diagnostics intentionally enforce distinct service-boundary and general exported-contract policy scopes.",
    "The rule checks module-level class declarations and direct class-expression values exported directly, through local export specifiers, or through a default identifier; re-exports and expressions wrapped in other calls require review.",
    "An extends clause satisfies the contract only when its target is a locally declared abstract class; imported base-class contracts require an explicit implements clause.",
    "Static factories and data-only classes without public instance methods are outside the contract requirement.",
  ],
  examples: [
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
      public: true,
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
