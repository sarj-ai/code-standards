/** @fileoverview prefer-immutable-module-constant — the documentation and executable examples of `@sarj/prefer-immutable-module-constant`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_IMMUTABLE_MODULE_CONSTANT_DOCUMENTATION = {
  summary: "Require module-level constant collections to expose readonly state.",
  rationale:
    "A const binding prevents reassignment but does not stop callers from mutating its array, object, Set, or Map contents.",
  remediation:
    "Expose literals with `as const` or a readonly type, and expose Set or Map values through ReadonlySet or ReadonlyMap.",
  category: "correctness",
  autofix: "safe",
  limitations: [
    "Automatic fixes add as const only to unannotated, unused private object/array literals in explicit modules with no eval; referenced or exported collections remain manual.",
    "Generated, test and JavaScript files are skipped. Private constants with observed direct or alias mutation are excluded; exported mutable collections remain advisory candidates. Reassigned aliases are conservatively followed, not flow-proven.",
    "Local type aliases are resolved before recognizing standard readonly types; imported or otherwise unknown type declarations are not inferred from their names. Readonly types have no runtime enforcement.",
  ],
  examples: [
    {
      id: "readonly-array-literal",
      title: "A module constant exposes a readonly literal",
      outcome: "no-match",
      files: [{ path: "src/constants.ts", source: "const VALUES = [1, 2, 3] as const;" }],
      focusPath: "src/constants.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "mutable-array-literal",
      title: "A module constant exposes a mutable array",
      outcome: "match",
      files: [{ path: "src/constants.ts", source: "const VALUES = [1, 2, 3];" }],
      focusPath: "src/constants.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "shadowed-readonly-alias",
      scenarioId: "type-binding",
      title: "A type named Readonly still exposes mutable properties",
      outcome: "match",
      files: [{ path: "src/constants.ts", source: "type Readonly = { voice: boolean };\nexport const TOOL_SUPPORT: Readonly = { voice: true };" }],
      focusPath: "src/constants.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "resolved-readonly-alias",
      scenarioId: "type-binding",
      title: "A local alias resolves to readonly properties",
      outcome: "no-match",
      files: [{ path: "src/constants.ts", source: "type ToolSupport = Readonly<{ voice: boolean }>;\nexport const TOOL_SUPPORT: ToolSupport = { voice: true };" }],
      focusPath: "src/constants.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; const VALUES = [1, 2, 3];" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; const VALUES = [1, 2, 3] as const;" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
