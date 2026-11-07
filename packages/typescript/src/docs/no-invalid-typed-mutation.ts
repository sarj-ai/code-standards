/** @fileoverview no-invalid-typed-mutation — the documentation and executable examples of `@sarj/no-invalid-typed-mutation`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_INVALID_TYPED_MUTATION_DOCUMENTATION = {
  summary: "Keep native object mutation APIs from writing incompatible values into declared property types.",
  rationale: "Object.assign, Reflect.set and property descriptors accept values that a normal typed property assignment rejects. They can invalidate a domain object's contract while subsequent reads retain its original type.",
  remediation: "Use an assignment that satisfies the declared property type, or construct and validate a complete replacement. Preserve any deliberate construction or external compatibility contract; do not cast away the incompatibility.",
  category: "correctness",
  defaultLevel: "error",
  autofix: "none",
  limitations: [
    "Requires type information and an explicitly annotated local const initialized with a plain own-data object literal. Only non-exported, stable bindings without escapes or nested captures qualify. Deletes and descriptors that can lock writability or configurability invalidate storage provenance. The closed non-union contract must declare the initialized data property; parameters, opaque constructors/factories, accessor, method, indexed, callable and unresolved generic targets are excluded.",
    "Inspects native Object.assign with one plain object-literal source, native Reflect.set with a static string key and no separate receiver, and native Object/Reflect.defineProperty with a plain value descriptor. Dynamic keys, spreads, accessors, API aliases, extra properties and multiple assign sources are excluded.",
    "Any, unknown, never, unresolved generic or overloaded property/value types are excluded because this check cannot prove their incompatibility. Type arguments and nested data fields are inspected with a 32-type recursion bound. Readonly fields are checked only for incompatible values; compatible writes are outside this rule. Under exact optional properties, authored write types are recovered only for direct non-transient declarations without mapped or generic substitution; other explicit-undefined writes can be missed.",
    "Scope-resolved globals and standard-library signatures establish API identity. File-local namespace escapes, aliases, direct replacements or reflective mutation of Object/Reflect invalidate that namespace. Visible Object.prototype mutation or escape invalidates both APIs because descriptors inherit its fields. Indirect monkey-patching and external proxy behavior are not inferred. Generated files are excluded; tests remain checked.",
  ],
  references: [
    "https://typescript-eslint.io/rules/no-unsafe-assignment/",
    "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Object/assign",
  ],
  examples: [
    { id: "compatible-property-write", title: "Preserve the declared field contract", outcome: "no-match", files: [{ path: "src/count.ts", source: 'const counter: { count: number } = { count: 1 }; Object.assign(counter, { count: 2 });' }], focusPath: "src/count.ts", expectedCount: 0, public: true },
    { id: "incompatible-property-write", title: "Do not bypass field compatibility through a generic mutation API", outcome: "match", files: [{ path: "src/count.ts", source: 'const counter: { count: number } = { count: 1 }; Object.assign(counter, { count: "invalid" }); counter.count.toFixed();' }], focusPath: "src/count.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
