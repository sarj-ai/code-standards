/** @fileoverview no-contradictory-type-predicate — the documentation and executable examples of `@sarj/no-contradictory-type-predicate`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_CONTRADICTORY_TYPE_PREDICATE_DOCUMENTATION = {
  summary: "Keep explicit type predicates consistent with their primitive, array or record membership check.",
  rationale: "TypeScript trusts an explicit type predicate without verifying its implementation. A contradictory check can admit the wrong primitive, overclaim a closed literal or empty domain, accept null as a non-null object, or remove valid alternatives from the false branch.",
  remediation: "Match the predicate to every value the check accepts and rejects. Check literal membership for a closed domain and exclude null when promising a non-null object. Use a boolean return for an intentional value filter; preserve required public and callback contracts.",
  category: "correctness",
  defaultLevel: "error",
  autofix: "safe",
  limitations: [
    "Automatic fixes replace the unsound predicate with boolean only for an unused private function declaration without overloads, exports, eval, comments in the predicate, or declaration-file ownership. Runtime checks are preserved; observed callable contracts remain manual.",
    "Requires type information, an explicit predicate over a directly named parameter and a single returned positive typeof equality for the same scope-resolved parameter. Both strict and loose equality and reversed operands are supported.",
    "Recognizes broad primitive targets, finite primitive literal/nullish unions and never, with unknown or fully classified primitive/nullish inputs. Closed input domains are checked against the actual target, including finite numeric enum members. Mixed broad-and-literal, branded, unique-symbol, structural, generic, asserted, declaration-only and multi-statement validators are excluded rather than guessed.",
    "For the intrinsic object target, typeof-object also admits null only when the declared input admits null and strictNullChecks is enabled. This narrow check does not infer structural property validation or classify other object/function relationships. Overloaded implementations, contextually typed callbacks and methods with class heritage or contextual object contracts retain their separate callable domain.",
    "Compiler-invalid predicate target/input relations and typeof comparisons impossible for the input remain with existing compiler and unnecessary-condition controls. This rule does not validate arbitrary predicates or runtime refinements. Generated files are excluded; tests remain checked.",
    "A sole native Array.isArray call on unknown cannot establish a plain primitive-element array target. Standard-library call signatures and an unshadowed Array binding are required. Element validators, any/unknown elements, tuples, enums, branded or opaque elements and independent callable contracts abstain. Visible Array or host-global aliases, mutation, escapes, extracted methods, any value constructor or unresolved computed-property access and unrelated Array namespace uses disable this proof: structural receiver types cannot establish runtime constructor identity. Native Reflect value uses and Object prototype/descriptor reflection or namespace aliases also withdraw authority. Indirect opaque runtime replacements are not inferred.",
    "For a same-file nongeneric named record with a required data property, a sole typeof-object check, optionally conjoined with a null exclusion, cannot establish that property from unknown or object input. Optional-only records, dictionaries, classes, imported/generic contracts and implementations with field checks are excluded. A non-null object without the required own property supplies the contradiction. The same unused-private predicate proof may remove its unobserved narrowing contract; observed callable contracts and sole named-type uses remain manual.",
  ],
  references: ["https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-5.html#inferred-type-predicates"],
  examples: [
    { id: "consistent-primitive-predicate", title: "Agree with the checked primitive", outcome: "no-match", files: [{ path: "src/guard.ts", source: 'function isText(value: unknown): value is string { return typeof value === "string"; }' }], focusPath: "src/guard.ts", expectedCount: 0, public: true },
    { id: "contradictory-primitive-predicate", title: "Do not promise a different primitive", outcome: "match", files: [{ path: "src/guard.ts", source: 'function isText(value: unknown): value is string { return typeof value === "number"; }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "closed-literal-check", scenarioId: "closed-literal-domain", title: "A closed input supplies the literal evidence", outcome: "no-match", files: [{ path: "src/guard.ts", source: 'function ready(value: "ready" | null): value is "ready" { return typeof value === "string"; }' }], focusPath: "src/guard.ts", expectedCount: 0, public: true },
    { id: "overclaimed-literal", scenarioId: "closed-literal-domain", title: "A string check admits other strings", outcome: "match", files: [{ path: "src/guard.ts", source: 'function ready(value: unknown): value is "ready" { return typeof value === "string"; }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "complete-object-check", scenarioId: "intrinsic-null", title: "Exclude null and recognize non-primitive functions", outcome: "no-match", files: [{ path: "src/guard.ts", source: 'function nonPrimitive(value: unknown): value is object { return (typeof value === "object" && value !== null) || typeof value === "function"; }' }], focusPath: "src/guard.ts", expectedCount: 0, public: true },
    { id: "object-check-admits-null", scenarioId: "intrinsic-null", title: "A typeof-object check also accepts null", outcome: "match", files: [{ path: "src/guard.ts", source: 'function nonPrimitive(value: unknown): value is object { return typeof value === "object"; }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "empty-domain-never-succeeds", scenarioId: "empty-domain", title: "An empty target has no successful member", outcome: "no-match", files: [{ path: "src/guard.ts", source: 'function impossible(value: unknown): value is never { return false; }' }], focusPath: "src/guard.ts", expectedCount: 0, public: true },
    { id: "empty-domain-check-succeeds", scenarioId: "empty-domain", title: "Numbers cannot belong to an empty target", outcome: "match", files: [{ path: "src/guard.ts", source: 'function impossible(value: unknown): value is never { return typeof value === "number"; }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "array-elements-unchecked", scenarioId: "array-elements", title: "Array membership alone does not prove text elements", outcome: "match", files: [{ path: "src/guard.ts", source: 'function texts(value: unknown): value is string[] { return Array.isArray(value); }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "array-elements-validated", scenarioId: "array-elements", title: "Establish the element domain at the boundary", outcome: "no-match", files: [{ path: "src/guard.ts", source: 'function texts(value: unknown): value is string[] { return Array.isArray(value) && value.every((item: unknown) => typeof item === "string"); }' }], focusPath: "src/guard.ts", expectedCount: 0, public: true },
    { id: "record-fields-unchecked", scenarioId: "record-fields", title: "Object membership does not establish required fields", outcome: "match", files: [{ path: "src/guard.ts", source: 'type Account = { id: string }; function account(value: unknown): value is Account { return typeof value === "object" && value !== null; }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "record-fields-validated", scenarioId: "record-fields", title: "Establish fields before promising the record", outcome: "no-match", files: [{ path: "src/guard.ts", source: 'type Account = { id: string }; function account(value: unknown): value is Account { return typeof value === "object" && value !== null && "id" in value && typeof value.id === "string"; }' }], focusPath: "src/guard.ts", expectedCount: 0, public: true },
    {
      id: "safe-autofix",
      title: "Retain an unused private filter without unsound narrowing",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; function isText(value: unknown): value is string { return typeof value === \"number\"; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; function isText(value: unknown): boolean { return typeof value === \"number\"; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
