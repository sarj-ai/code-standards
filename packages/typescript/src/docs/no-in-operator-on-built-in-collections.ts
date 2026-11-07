/** @fileoverview no-in-operator-on-built-in-collections — the documentation and executable examples of `@sarj/no-in-operator-on-built-in-collections`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_IN_OPERATOR_ON_BUILT_IN_COLLECTIONS_DOCUMENTATION = {
  summary:
    "Do not use the `in` operator to test entries in built-in Map and Set collections.",
  rationale:
    "The `in` operator checks properties on the collection object and its prototype, while `.has()` checks stored entries. The similar spelling can silently test the wrong namespace.",
  remediation:
    "Use `collection.has(key)` for entry membership. Use `Reflect.has(collection, property)` when prototype-aware property lookup or Proxy `has` behavior is intentional.",
  category: "correctness",
  since: "15.17.14",
  autofix: "safe",
  limitations: [
    "The receiver type must resolve directly to a default-library Map, ReadonlyMap, WeakMap, Set, ReadonlySet, or WeakSet declaration; type aliases, unions, intersections, type parameters, subclasses, structural lookalikes, any, unknown, and generated files are excluded.",
    "Automatic fixes use Reflect.has only for a sole exported ordinary function with an explicit boolean return annotation and a literal-string property check on its single direct collection parameter, with no comments, other statements, source callouts or shadowed Reflect. This preserves existing property semantics and Proxy has-traps; inferred or explicit type predicates and other cases remain manual, and .has() is never inferred.",
    "Plain objects, arrays, TypeScript object-shape narrowing, private-brand checks, and for-in statements are not checked.",
  ],
  examples: [
    {
      id: "map-entry-membership",
      title: "Use Map.has for entry membership",
      outcome: "match",
      files: [
        {
          path: "src/cache.ts",
          source:
            "declare const cache: Map<string, object>; declare const key: string; if (key in cache) use(cache);",
        },
      ],
      focusPath: "src/cache.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "object-property-narrowing",
      title: "Preserve ordinary object property narrowing",
      outcome: "no-match",
      files: [
        {
          path: "src/cache.ts",
          source:
            "declare const value: { id: string } | { slug: string }; if ('id' in value) use(value.id);",
        },
      ],
      focusPath: "src/cache.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven source-owned correction",
      outcome: "match",
      files: [
        {
          path: "src/autofix-example.ts",
          source:
            "export function hasSize(cache: Map<string, object>): boolean { return 'size' in cache; }",
        },
      ],
      fixedFiles: [
        {
          path: "src/autofix-example.ts",
          source:
            "export function hasSize(cache: Map<string, object>): boolean { return Reflect.has(cache, 'size'); }",
        },
      ],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
