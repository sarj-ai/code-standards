/** @fileoverview no-redundant-optional-array-default — the documentation and executable examples of `@sarj/no-redundant-optional-array-default`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_REDUNDANT_OPTIONAL_ARRAY_DEFAULT_DOCUMENTATION = {
  summary: "Remove `.optional()` immediately inside a Zod array default.",
  rationale:
    "An outer default already accepts undefined array input, so the inner optional wrapper adds no state or fallback behavior.",
  remediation:
    "Keep the array default and remove the immediately preceding `.optional()` call.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Only syntactically local Zod array chains with adjacent `.optional().default(...)` calls are checked.",
    "Imports must name the official zod package or its subpaths; relative modules and unproven npm aliases are excluded.",
    "String, scalar, tuple, set, record, aliased, composed, and dynamically constructed schemas are excluded.",
    "The reversed `.default(...).optional()` order is preserved because its outer optional can return undefined instead of the default.",
    "Defaults must be literal arrays or synchronous functions returning one literal array; dynamic or undefined fallbacks are excluded because Zod 3 reparses the fallback.",
    "Automatic fixes require a whole module containing only one explicit zod/v3 namespace import and one unused unannotated private const with exact z.array(z.string()).optional().default([]). Other findings remain manual: exported introspection and supported Zod 4 constructor hooks observe the removed wrapper.",
    "Calls containing comments are excluded so the fix never deletes authored context.",
    "Test and generated files are excluded.",
  ],
  examples: [
    {
      id: "array-default",
      title: "Default an omitted list directly",
      outcome: "no-match",
      files: [
        {
          path: "src/schema.ts",
          source:
            'import { z } from "zod"; const Items = z.array(z.string()).default([]);',
        },
      ],
      focusPath: "src/schema.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "optional-array-default",
      title: "Do not wrap a defaulted list in a redundant optional",
      outcome: "match",
      files: [
        {
          path: "src/schema.ts",
          source:
            'import { z } from "zod"; const Items = z.array(z.string()).optional().default([]);',
        },
      ],
      focusPath: "src/schema.ts",
      expectedCount: 1,
      public: true,
    },

    {
      id: "unrelated-relative-builder",
      title: "Preserve an unrelated builder in a directory named zod",
      outcome: "no-match",
      files: [
        {
          path: "src/my-zod/index.ts",
          source:
            'export const z = { string: () => "string", array: (_element: string) => ({ optional: () => ({ default: (value: readonly string[]) => ({ value, optional: true }) }), default: (value: readonly string[]) => ({ value, optional: false }) }) };',
        },
        {
          path: "src/schema.ts",
          source:
            'import { z } from "./my-zod/index.js"; export const Items = z.array(z.string()).optional().default([]);',
        },
      ],
      focusPath: "src/schema.ts",
      expectedCount: 0,
      public: true,
      scenarioId: "module-identity",
    },
    {
      id: "official-zod-subpath-array",
      title: "Official Zod subpaths retain the finding for manual review",
      outcome: "match",
      files: [
        {
          path: "src/schema.ts",
          source:
            'import { array, string } from "zod/v4"; const Items = array(string()).optional().default([]);',
        },
      ],
      focusPath: "src/schema.ts",
      expectedCount: 1,
      public: true,
      scenarioId: "module-identity",
    },
    {
      id: "safe-autofix",
      title: "Remove a private legacy wrapper without constructor observers",
      outcome: "match",
      files: [
        {
          path: "src/autofix-example.ts",
          source:
            'import { z } from "zod/v3"; const Items = z.array(z.string()).optional().default([]);',
        },
      ],
      fixedFiles: [
        {
          path: "src/autofix-example.ts",
          source:
            'import { z } from "zod/v3"; const Items = z.array(z.string()).default([]);',
        },
      ],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
