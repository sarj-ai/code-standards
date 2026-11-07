/** @fileoverview no-partial-type-predicate — the documentation and executable examples of `@sarj/no-partial-type-predicate`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_PARTIAL_TYPE_PREDICATE_DOCUMENTATION = {
  summary: "Do not give a partial primitive filter an explicit type predicate that excludes valid values in the false branch.",
  rationale: "Type predicates narrow both branches, and TypeScript trusts their implementation. A positive-number or non-empty-string predicate can return false for a value belonging to its promised type, causing callers to treat that value as a different type.",
  remediation: "Use a boolean return for an intentional value filter, or recognize every member of the promised type. Preserve required callback and public contracts; a refined domain may need a distinct validated type. Recheck false-branch callers when changing a predicate.",
  category: "correctness",
  defaultLevel: "error",
  autofix: "safe",
  limitations: [
    "Automatic fixes replace the unsound predicate with boolean only for an unused private function declaration without overloads, exports, eval, comments in the predicate, or declaration-file ownership. Runtime checks are preserved; observed callable contracts remain manual.",
    "Requires type information and a non-generic, non-async function with one directly annotated parameter, an explicit broad string/number/bigint/boolean predicate and a single return. Literal, branded, structural, multi-primitive union, assertion, method and overloaded contracts are excluded; contextually typed callbacks are preserved.",
    "Recognizes double-negation truthiness, a boolean parameter return or one same-kind literal comparison, optionally after a matching typeof equality. Without a typeof check, the input must already belong to the target primitive, except for double negation. String length comparisons use only concrete witnesses up to 256 characters. Arithmetic, dynamic bounds and complex boolean conditions are not inferred.",
    "A broad string predicate returning local Schema.safeParse(parameter).success is also checked for a locally unchanged official z.uuid() or z.string().uuid() schema. The checker must resolve the namespace to installed node_modules/zod declaration files; local path aliases and opaque module resolution abstain. The const schema permits local parse/type/direct-export reads; every safeParse call must have exactly one direct argument, without options or spreads. Local aliases, method writes and opaque consumers abstain. Direct export alone is not mutation, but external consumer monkey-patching is not proved absent. Other value uses of its imported Zod namespace cause abstention. Transforms, brands, custom schemas, imported schemas and dynamic parse calls are excluded. Visible RegExp capabilities, regex literals or dynamic evaluation invalidate this initial native-pattern proof; external runtime monkeypatches are not inferred. The same unused-private-declaration fix boundary applies; observed or exported predicates remain manual.",
    "A concrete member of the promised broad primitive must demonstrably return false. Numeric witnesses must also be assignable as literals to the declared input: broad number assignability alone does not prove membership in a numeric enum. Compiler-invalid target/input relations, any/never/generic inputs and opaque implementations abstain. This rule does not discourage total boundary guards or infer branded refinements. Generated files are excluded; tests remain checked.",
  ],
  references: ["https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-5.html#inferred-type-predicates"],
  examples: [
    { id: "boolean-value-filter", title: "Keep an intentional value filter boolean", outcome: "no-match", files: [{ path: "src/filter.ts", source: 'function isPositive(value: number): boolean { return value > 0; }' }], focusPath: "src/filter.ts", expectedCount: 0, public: true },
    { id: "partial-number-predicate", title: "Zero remains a number when the predicate returns false", outcome: "match", files: [{ path: "src/guard.ts", source: 'function isPositive(value: unknown): value is number { return typeof value === "number" && value > 0; }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "partial-uuid-predicate", scenarioId: "uuid", title: "A rejected UUID candidate can still be a string", outcome: "match", files: [{ path: "src/guard.ts", source: 'import { z } from "zod"; export const UuidSchema: z.ZodUUID = z.uuid(); export function isUuid(value: unknown): value is string { return UuidSchema.safeParse(value).success; }' }], installedDependencies: [{ module: "zod", version: "4.6.7" }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "boolean-uuid-filter", scenarioId: "uuid", title: "Keep a UUID value filter boolean", outcome: "no-match", files: [{ path: "src/filter.ts", source: 'import { z } from "zod"; export const UuidSchema: z.ZodUUID = z.uuid(); export function isUuid(value: unknown): boolean { return UuidSchema.safeParse(value).success; }' }], installedDependencies: [{ module: "zod", version: "4.6.7" }], focusPath: "src/filter.ts", expectedCount: 0, public: true },
    {
      id: "safe-autofix",
      title: "Retain an unused private filter without unsound narrowing",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; function isPositive(value: unknown): value is number { return typeof value === \"number\" && value > 0; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; function isPositive(value: unknown): boolean { return typeof value === \"number\" && value > 0; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
