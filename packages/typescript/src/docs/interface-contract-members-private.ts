/** @fileoverview interface-contract-members-private — the documentation and executable examples of `@sarj/interface-contract-members-private`. */

import type { RuleDocumentation } from "../documentation.js";

export const INTERFACE_CONTRACT_MEMBERS_PRIVATE_DOCUMENTATION = {
  summary: "Require methods outside an implemented interface contract to use ECMAScript private names.",
  rationale: "An implementing class should expose exactly its declared interface while keeping implementation helpers runtime-private.",
  remediation: "Add the method to the interface when it is public API, or make it `#private` and remove external or inherited access.",
  category: "architecture",
  autofix: "safe",
  limitations: ["Automatic conversion is limited to unused private module/block classes without heritage, decorators, computed members, static execution, or eval; referenced classes remain manual.",
    "Only concrete classes with an explicit `implements` clause are checked; constructors, static members, protected extension hooks, and overrides are excluded.",
    "Inherited interface members are resolved by TypeScript. Computed names are excluded because their contract identity is not stable syntax.",
    "The rule abstains for the whole class when TypeScript cannot resolve any implemented contract, avoiding false positives for missing or unavailable package declarations.",
    "Referenced classes remain report-only because a public member can have consumers in another source file; the developer must choose whether to extend the interface or privatize it.",
    "TypeScript-private members are left to prefer-ecmascript-private-members so one concern produces one diagnostic.",
  ],
  examples: [
    {
      id: "exact-interface-surface",
      title: "Keep helpers behind the runtime boundary",
      outcome: "no-match",
      files: [{ path: "src/store.ts", source: "interface Store { load(): void } class DiskStore implements Store { load() { this.#read(); } #read() {} }" }],
      focusPath: "src/store.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "extra-public-method",
      title: "Do not grow an undeclared public surface",
      outcome: "match",
      files: [{ path: "src/store.ts", source: "interface Store { load(): void } class DiskStore implements Store { load() { this.read(); } read() {} }" }],
      focusPath: "src/store.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; interface Store { load(): void } class DiskStore implements Store { load() { this.read(); } read() {} }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; interface Store { load(): void } class DiskStore implements Store { load() { this.#read(); } #read() {} }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
