/** @fileoverview named-child-schema-type — the documentation and executable examples of `@sarj/named-child-schema-type`. */

import type { RuleDocumentation } from "../documentation.js";

export const NAMED_CHILD_SCHEMA_TYPE_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Reference a named Zod record child's complete schema type instead of repeating its explicit annotation.",
  rationale: "Repeating a child schema's generic contract creates a second maintained declaration even though the record already uses that child at runtime.",
  remediation: "Replace only the matching record type argument with `typeof ChildSchema`, or share one explicit named schema type alias between child and record to retain an independently named public contract. Keep the outer annotation required by isolatedDeclarations and every runtime schema operation.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Only direct module-level const z.record calls with two arguments, a ZodRecord annotation, and an earlier local const child with a complete explicit Zod type are inspected.",
    "The entire generic child annotation must match token for token; input/output, defaults, transforms, readonly modifiers and brands are never compared by output shape alone.",
    "Bare leaf types, broad ZodType constraints, type queries, imported or unqualified type references, annotation cycles, comments on the repeated argument, mutable bindings and generated files are excluded.",
    "Import aliases and namespace imports resolve through scope bindings. Independent public contract pins can use one shared named type alias or an exact reasoned suppression; runtime validation and outer annotations are preserved.",
  ],
  examples: [
    { id: "named-child", title: "Reference the named child contract", outcome: "no-match", files: [{ path: "src/record.ts", source: 'import { z } from "zod"; const KeySchema: z.ZodEnum<{ a: "a"; b: "b" }> = z.enum(["a", "b"]); export const RecordSchema: z.ZodRecord<typeof KeySchema, z.ZodString> = z.record(KeySchema, z.string());' }], focusPath: "src/record.ts", expectedCount: 0, public: true },
    { id: "copied-child", title: "Do not repeat the complete child annotation", outcome: "match", files: [{ path: "src/record.ts", source: 'import { z } from "zod"; const KeySchema: z.ZodEnum<{ a: "a"; b: "b" }> = z.enum(["a", "b"]); export const RecordSchema: z.ZodRecord<z.ZodEnum<{ a: "a"; b: "b" }>, z.ZodString> = z.record(KeySchema, z.string());' }], focusPath: "src/record.ts", expectedCount: 1, public: true },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "import { z } from \"zod\"; const KeySchema: z.ZodEnum<{ a: \"a\" }> = z.enum([\"a\"]); const RecordSchema: z.ZodRecord<z.ZodEnum<{ a: \"a\" }>, z.ZodString> = z.record(KeySchema, z.string());" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "import { z } from \"zod\"; const KeySchema: z.ZodEnum<{ a: \"a\" }> = z.enum([\"a\"]); const RecordSchema: z.ZodRecord<typeof KeySchema, z.ZodString> = z.record(KeySchema, z.string());" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
