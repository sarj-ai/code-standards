/** @fileoverview prefer-ecmascript-private-members — the documentation and executable examples of `@sarj/prefer-ecmascript-private-members`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_ECMASCRIPT_PRIVATE_MEMBERS_DOCUMENTATION = {
  summary: "Prefer ECMAScript `#private` class members over TypeScript-only `private` members.",
  rationale: "ECMAScript private names enforce encapsulation at runtime instead of erasing the boundary during compilation.",
  remediation: "Review reflection, instance escape and framework contracts before replacing TypeScript privacy with ECMAScript private names and updating references.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Ambient, abstract, computed, decorated, override, parameter-property, and generated declarations are excluded.",
    "Automatic conversion is limited to unused private module/block classes with no heritage, decorators, computed members, static execution, or eval. Other migration is report-only: type information cannot prove that instances or constructors never escape through this, or that reflection and framework serialization do not observe ordinary private properties.",
  ],
  references: ["https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Classes/Private_elements"],
  examples: [
    {
      id: "runtime-private-member",
      title: "Use runtime-enforced privacy",
      outcome: "no-match",
      files: [{ path: "src/vault.ts", source: "class Vault { #read() { return 1; } open() { return this.#read(); } }" }],
      focusPath: "src/vault.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "typescript-private-member",
      title: "Do not erase a privacy boundary",
      outcome: "match",
      files: [{ path: "src/vault.ts", source: "class Vault { private read() { return 1; } open() { return this.read(); } }" }],
      focusPath: "src/vault.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; class Vault { private read() { return 1; } open() { return this.read(); } }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; class Vault { #read() { return 1; } open() { return this.#read(); } }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
