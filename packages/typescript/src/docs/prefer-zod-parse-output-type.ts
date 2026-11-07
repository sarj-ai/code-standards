/** @fileoverview prefer-zod-parse-output-type — the documentation and executable examples of `@sarj/prefer-zod-parse-output-type`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Consider deriving validated return contracts from the Zod schema when the schema owns the contract.",
  rationale: "A hand-written contract can drift from the runtime-validated value. Schema ownership determines whether deriving the type preserves the domain architecture.",
  remediation: "When the schema owns the contract, derive it with `z.output<typeof Schema>`. Preserve independently owned domain and public API contracts, and validate schema compatibility with those contracts.",
  category: "correctness",
  autofix: "safe",
  limitations: [
    "Requires TypeScript type information and a returned output from a module-level local Zod object schema's `.parse()` or `.safeParse()` result.",
    "Same-module name-correlated twins that `prefer-zod-infer` can prove are left to that established rule; this companion owns richer or renamed same-module and cross-module contracts proven by parse-return data flow.",
    "Only a single plain non-generic object interface or object type alias with exact property keys and bidirectional assignability is reported.",
    "Direct returns, nullish conditional branches, and one immutable local parse-result binding are followed; second aliases, assignments, helper calls, imported schemas, and other indirect data flow are intentionally excluded.",
    "Contracts returned from more than one distinct local schema are excluded because no single schema has unambiguous ownership.",
    "Readonly, augmented, indexed, callable, generated, constrained, any, unknown, and never contracts are excluded rather than guessed.",
    "Nested contracts must preserve property keys, optionality and readonly behavior through aliases, containers and unambiguous unions. Distinct nested classes, accessor or method declarations, opaque members, ambiguous unions, or graphs beyond 128 compared pairs or 16 union alternatives are excluded.",
    "Explicit callable bindings, independently annotated contextual callbacks or object members, and class members fulfilling an annotated heritage contract retain ownership of their named output contract. Inference from the function body alone does not establish ownership; independent helpers remain eligible.",
    "Automatic fixes replace only the bare return annotation of an unused private nongeneric synchronous function returning one direct local-schema parse result. The removed named contract must retain an independent top-level exported type-alias or direct type-export read; references in other removable annotations/assertions or its own definition cannot keep it live. Sole-use contracts, multiple consumers, public/callback/async/nullish/aliased returns, comments, shadowing and missing original Zod import provenance preserve manual ownership; schemas and domain declarations are never moved or exported.",
  ],
  examples: [
    {
      id: "schema-derived-return",
      title: "Derive the validated return contract",
      outcome: "no-match",
      files: [
        {
          path: "src/row.ts",
          source: 'import { z } from "zod"; const RowSchema = z.object({ id: z.string() }); type Row = z.output<typeof RowSchema>; function load(): Row { return RowSchema.parse({}); }',
        },
      ],
      focusPath: "src/row.ts",
      expectedCount: 0,
      public: true, installedDependencies: [{ module: "zod", version: "4.6.7" }],
    },
    {
      id: "hand-written-parsed-return",
      title: "Do not hand-write the parsed return shape",
      outcome: "match",
      files: [
        {
          path: "src/contracts.ts",
          source: "export interface ParsedRow { id: string }",
        },
        {
          path: "src/row.ts",
          source: 'import { z } from "zod"; import type { ParsedRow } from "./contracts.js"; const RowSchema = z.object({ id: z.string() }); function load(): ParsedRow { return RowSchema.parse({}); }',
        },
      ],
      focusPath: "src/row.ts",
      expectedCount: 1,
      public: true, installedDependencies: [{ module: "zod", version: "4.6.7" }],
    },
    {
      id: "safe-autofix",
      title: "Derive an unused private parser return from its local schema",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "import { z } from \"zod\"; interface ParsedRow { id: string } export type KeptParsedRow = ParsedRow; const RowSchema = z.object({ id: z.string() }); function load(): ParsedRow { return RowSchema.parse({}); }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "import { z } from \"zod\"; interface ParsedRow { id: string } export type KeptParsedRow = ParsedRow; const RowSchema = z.object({ id: z.string() }); function load(): z.output<typeof RowSchema> { return RowSchema.parse({}); }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
      installedDependencies: [{ module: "zod", version: "4.6.7" }],
    },
  ],
} as const satisfies RuleDocumentation;
