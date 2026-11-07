/** @fileoverview no-json-stringify-object-equality — the documentation and executable examples of `@sarj/no-json-stringify-object-equality`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_JSON_STRINGIFY_OBJECT_EQUALITY_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Do not use JSON serialization as structural object equality.",
  rationale:
    "JSON text equality depends on property insertion order and serialization behavior, so semantically equal objects can compare unequal and distinct values can collapse together.",
  remediation:
    "Compare an explicit domain projection structurally, or use a reviewed canonical serializer when JSON semantics are required.",
  category: "correctness",
  autofix: "safe",
  limitations: [
    "Only direct binary comparisons between two unshadowed global JSON.stringify calls, including stable const destructured aliases of that global, are checked.",
    "Primitive-only arrays are excluded when TypeScript can prove their element types.",
    "Mutable, defaulted, reassigned, transitive and unknown aliases, stored serialization results, custom JSON objects, tests, generated files, and equality hidden inside helper calls are excluded.",
    "Automatic fixes only reuse an already called private ordinary comparator in a complete comment-free two-declaration module. Its two inline record parameter types must contain the same ordered unique string fields, including an already-authored own non-callable string toJSON field; its sole return compares every corresponding field with strict equality and conjunction. The sole export is an ordinary zero-argument function explicitly returning boolean[], whose sole returned array contains the existing comparator call and one direct strict JSON comparison of fresh literal records with those exact ordered fields and primitive string values. Imports, ambient declarations, callbacks, computed/spread/getter properties, prototype-related keys, type parameters and all other expressions remain manual.",
    "The own primitive toJSON data field is required in every literal and is never introduced by the fix: it prevents an inherited Object.prototype.toJSON hook from changing serialization. The direct unshadowed JSON.stringify intrinsic must retain its standard behavior; no new helper, field, import or domain name is chosen.",
  ],
  examples: [
    {
      id: "domain-comparator",
      title: "Use an explicit structural comparator",
      outcome: "no-match",
      files: [
        {
          path: "src/compare.ts",
          source:
            "type RecordState = { id: string; state: string };\nfunction sameRecord(actual: RecordState, expected: RecordState): boolean { return actual.id === expected.id && actual.state === expected.state; }\nconst same = sameRecord({ id: '1', state: 'ready' }, { state: 'ready', id: '1' });",
        },
      ],
      focusPath: "src/compare.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "serialized-object-equality",
      title: "Do not compare object serialization",
      outcome: "match",
      files: [
        {
          path: "src/compare.ts",
          source:
            "const same = JSON.stringify({ id: '1', state: 'ready' }) === JSON.stringify({ state: 'ready', id: '1' });",
        },
      ],
      focusPath: "src/compare.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Reuse the existing comparator for an exact string record domain",
      outcome: "match",
      files: [
        {
          path: "src/compare.ts",
          source:
            "function sameShape(a: { id: string; state: string; toJSON: string }, b: { id: string; state: string; toJSON: string }): boolean { return a.id === b.id && a.state === b.state && a.toJSON === b.toJSON; }\nexport function choices(): boolean[] { return [sameShape({ id: '1', state: 'ready', toJSON: 'data' }, { id: '1', state: 'ready', toJSON: 'data' }), JSON.stringify({ id: '1', state: 'ready', toJSON: 'data' }) === JSON.stringify({ id: '2', state: 'ready', toJSON: 'data' })]; }",
        },
      ],
      fixedFiles: [
        {
          path: "src/compare.ts",
          source:
            "function sameShape(a: { id: string; state: string; toJSON: string }, b: { id: string; state: string; toJSON: string }): boolean { return a.id === b.id && a.state === b.state && a.toJSON === b.toJSON; }\nexport function choices(): boolean[] { return [sameShape({ id: '1', state: 'ready', toJSON: 'data' }, { id: '1', state: 'ready', toJSON: 'data' }), sameShape({ id: '1', state: 'ready', toJSON: 'data' }, { id: '2', state: 'ready', toJSON: 'data' })]; }",
        },
      ],
      focusPath: "src/compare.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
