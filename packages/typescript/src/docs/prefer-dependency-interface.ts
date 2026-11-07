/** @fileoverview prefer-dependency-interface — the documentation and executable examples of `@sarj/prefer-dependency-interface`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_DEPENDENCY_INTERFACE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Annotate retained collaborators with their existing interface when the consumer uses only that contract.",
  rationale: "A concrete annotation can require private implementation identity even when a declared interface covers every consumed operation.",
  remediation: "Use the existing interface on the injected parameter. Keep concrete annotations for implementation-specific capabilities.",
  category: "architecture",
  limitations: [
    "Checks private readonly constructor parameter properties, an empty constructor body, and a local concrete class declaring exactly one local interface. Every direct this-property consumer must access an interface member.",
    "Interface/class inheritance, imports, dynamic members, escapes, implementation-specific reads, decorators, generics, mutable dependencies and protected properties remain unresolved. The compiler owns signature compatibility. No contract or automatic rewrite is invented.",
  ],
  examples: [
    { id: "concrete-store", title: "The consumer uses only the interface", outcome: "match", files: [{ path: "service.ts", source: "interface Store { read(): string } class SqlStore implements Store { private value = 'ok'; read() { return this.value; } } class Service { constructor(private readonly store: SqlStore) {} run() { return this.store.read(); } }" }], focusPath: "service.ts", expectedCount: 1, public: true },
    { id: "interface-store", title: "Accept another implementation", outcome: "no-match", files: [{ path: "service.ts", source: "interface Store { read(): string } class Service { constructor(private readonly store: Store) {} run() { return this.store.read(); } }" }], focusPath: "service.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
