/** @fileoverview no-enum — the documentation and executable examples of `@sarj/no-enum`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_ENUM_DOCUMENTATION = {
  summary: "Disallow TypeScript `enum`; use string-literal unions or `as const` objects instead.",
  rationale:
    "Literal unions keep type-only domains explicit, while constant objects make runtime values deliberate. This policy also avoids compiler-dependent const-enum inlining contracts.",
  remediation:
    "Use a literal union or an `as const` object after checking runtime member access, numeric reverse mappings, serialized values, and public consumers.",
  category: "maintainability",
  autofix: "safe",
  limitations: ["This is an explicit style policy for regular and const enums, not a claim that every enum emits an object. Generated files and configured exclusions are preserved. Automatic conversion is limited to unused private ambient enums with literal string values; runtime enums and observed nominal contracts remain manual."],
  references: ["https://www.typescriptlang.org/docs/handbook/enums.html"],
  examples: [
    {
      id: "string-literal-union",
      title: "A string-literal union has no emitted runtime enum",
      outcome: "no-match",
      files: [{ path: "src/status.ts", source: 'type Status = "active" | "inactive";' }],
      focusPath: "src/status.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "numeric-enum",
      title: "A numeric enum emits a mutable runtime object",
      outcome: "match",
      files: [{ path: "src/status.ts", source: "enum Status { Active, Inactive }" }],
      focusPath: "src/status.ts",
      expectedCount: 1,
      public: true,
    },
    { id: "authored-after-comment", scenarioId: "native-header-boundary", title: "Keep executable authored code in scope", outcome: "match", files: [{ path: "src/status.ts", source: "// ordinary header\u2028const marker=\"auto-generated file\"; enum Mode {Start} console.log(Mode.Start, marker);" }], focusPath: "src/status.ts", expectedCount: 1, public: true },
    { id: "generated-header", scenarioId: "native-header-boundary", title: "Respect a native generated banner", outcome: "no-match", files: [{ path: "src/status.ts", source: "// auto-generated file\u2028const marker=\"auto-generated file\"; enum Mode {Start} console.log(Mode.Start, marker);" }], focusPath: "src/status.ts", expectedCount: 0, public: true },
    {
      id: "safe-autofix",
      title: "Replace an unused ambient string enum with an erased union",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; declare enum Status { Active = 'active', Inactive = 'inactive' }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; type Status = 'active' | 'inactive';" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
