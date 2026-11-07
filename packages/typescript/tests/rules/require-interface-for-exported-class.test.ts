// vitest: shared-module-graph
import rule from "../../src/rules/require-interface-for-exported-class.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

const REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION = {
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
} as const;

RULE_TESTER.run("require-interface-for-exported-class", rule, {
  valid: [
    {
      filename: "src/store.js",
      code: "export class Store { read() { return 1; } }",
    },
    {
      filename: "src/store.jsx",
      code: "export class Store { read() { return 1; } }",
    },
    {
      filename: "src/store.mjs",
      code: "export class Store { read() { return 1; } }",
    },
    {
      filename: "src/store.cjs",
      code: "export class Store { read() { return 1; } }",
    },
    REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION.examples[0].files[0]
      .source,
    "export abstract class ArtifactStore { abstract read(id: string): Promise<Uint8Array>; }",
    "abstract class BaseStore { abstract read(): void; } export class ArtifactStore extends BaseStore { read() {} }",
    "abstract class BaseStore { abstract read(): void; } export const ArtifactStore = class extends BaseStore { read() {} };",
    "interface Storage { read(): void; } export const ArtifactStore = class implements Storage { read() {} };",
    "export class ArtifactRecord { constructor(readonly id: string) {} }",
    {
      filename: "src/artifact-store.test.ts",
      code: "export class ArtifactStore { read() {} }",
    },
  ],
  invalid: [
    {
      name: "reuses the existing direct factory return contract",
      filename: "src/service.ts",
      code: REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION.examples[2]
        .files[0].source,
      output:
        REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION.examples[2]
          .fixedFiles[0].source,
      errors: [{ messageId: "requireContract" }],
    },

    {
      code: REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION.examples[1]
        .files[0].source,
      errors: [
        { messageId: "requireContract", data: { name: "ArtifactStore" } },
      ],
    },
    {
      code: "export default class { run = () => undefined; }",
      errors: [{ messageId: "requireContract", data: { name: "default" } }],
    },
    {
      code: "class InternalStore { read() {} } export { InternalStore };",
      errors: [
        { messageId: "requireContract", data: { name: "InternalStore" } },
      ],
    },
    {
      code: "class ArtifactStore { read() {} } export default ArtifactStore;",
      errors: [
        { messageId: "requireContract", data: { name: "ArtifactStore" } },
      ],
    },
    {
      code: "class BaseStore { read() {} } export class ArtifactStore extends BaseStore { read() {} }",
      errors: [
        { messageId: "requireContract", data: { name: "ArtifactStore" } },
      ],
    },
    {
      code: "export class ArtifactStore { get current() { return 'value'; } }",
      errors: [
        { messageId: "requireContract", data: { name: "ArtifactStore" } },
      ],
    },
    {
      code: "export const ArtifactStore = class { read() {} };",
      errors: [
        { messageId: "requireContract", data: { name: "ArtifactStore" } },
      ],
    },
    {
      code: "const InternalStore = class { read() {} }; export { InternalStore as ArtifactStore };",
      errors: [
        { messageId: "requireContract", data: { name: "ArtifactStore" } },
      ],
    },
    {
      code: "const ArtifactStore = class { read() {} }; export default ArtifactStore;",
      errors: [
        { messageId: "requireContract", data: { name: "ArtifactStore" } },
      ],
    },
    {
      code: "export default class { get current() { return 'value'; } }",
      errors: [{ messageId: "requireContract", data: { name: "default" } }],
    },
  ],
});
