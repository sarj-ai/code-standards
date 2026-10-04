/**
 * @fileoverview no-in-operator-on-built-in-collections — use collection membership APIs for locally proven built-in collections.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-in-operator-on-built-in-collections.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, SourceCode, Variable } from "@oxlint/plugins";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { resolveArrayBinding, unwrapArrayExpression } from "./_array-method.js";
import { isGeneratedFile } from "./_paths.js";

export const NO_IN_OPERATOR_ON_BUILT_IN_COLLECTIONS_DOCUMENTATION = {
  summary:
    "Use entry membership rather than property lookup on locally identified built-in collections.",
  rationale:
    "The in operator checks object properties instead of Map or Set entries.",
  remediation:
    "Use .has() for entries or Reflect.has() for intentional property lookup.",
  category: "correctness",
  limitations: [
    "Checks unshadowed Map, ReadonlyMap, WeakMap, Set, ReadonlySet and WeakSet annotations, direct constructors and stable local aliases.",
    "Imported or inferred return types, member values, local type aliases, subclasses, unions, intersections and reassigned bindings are not resolved. Global library augmentation cannot be distinguished without a compiler.",
    "Generated sources are excluded. No autofix changes property membership into entry membership.",
  ],
  examples: [
    {
      id: "map-entry-membership",
      title: "Use Map.has for entry membership",
      outcome: "match",
      files: [
        {
          path: "src/cache.ts",
          source: 'const cache = new Map<string, object>(); "id" in cache;',
        },
      ],
      focusPath: "src/cache.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "object-property-narrowing",
      title: "Preserve object property narrowing",
      outcome: "no-match",
      files: [
        {
          path: "src/cache.ts",
          source:
            'declare const value: { id: string } | { slug: string }; if ("id" in value) use(value.id);',
        },
      ],
      focusPath: "src/cache.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const COLLECTIONS: ReadonlySet<string> = new Set([
  "Map",
  "ReadonlyMap",
  "WeakMap",
  "Set",
  "ReadonlySet",
  "WeakSet",
]);
function knownCollection(
  sourceCode: SourceCode,
  node: ESTree.Node,
  visited = new Set<Variable>(),
): boolean {
  node = unwrapArrayExpression(node);
  if (node.type === "NewExpression")
    return collectionName(sourceCode, node.callee);
  if (node.type !== "Identifier") return false;
  const variable = resolveArrayBinding(sourceCode, node);
  if (
    variable === null ||
    visited.has(variable) ||
    variable.references.some(
      (reference) => reference.isWrite() && !reference.init,
    )
  )
    return false;
  visited.add(variable);
  for (const identifier of variable.identifiers) {
    const type = identifier.typeAnnotation?.typeAnnotation;
    if (
      type?.type === "TSTypeReference" &&
      collectionName(sourceCode, type.typeName)
    )
      return true;
  }
  for (const definition of variable.defs) {
    if (
      definition.type === "Variable" &&
      definition.node.type === "VariableDeclarator" &&
      definition.node.init !== null &&
      definition.node.parent.type === "VariableDeclaration" &&
      definition.node.parent.kind === "const"
    ) {
      return knownCollection(sourceCode, definition.node.init, visited);
    }
  }
  return false;
}

function collectionName(sourceCode: SourceCode, node: ESTree.Node): boolean {
  if (node.type !== "Identifier" || !COLLECTIONS.has(node.name)) return false;
  const binding = resolveArrayBinding(sourceCode, node);
  return binding === null || binding.defs.length === 0;
}
export default createRule({
  name: "no-in-operator-on-built-in-collections",
  documentation: NO_IN_OPERATOR_ON_BUILT_IN_COLLECTIONS_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description: NO_IN_OPERATOR_ON_BUILT_IN_COLLECTIONS_DOCUMENTATION.summary,
    },
    schema: [],
    messages: {
      ambiguousCollectionIn:
        "`in` checks collection properties, not entries. Use `.has()` for entries or `Reflect.has()` for intentional property lookup.",
    },
  },
  defaultOptions: [],
  createOnce(context) {
    let generated = false;
    return {
      Program(): void {
        generated = isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text);
      },
      BinaryExpression(node): void {
        if (
          !generated &&
          node.operator === "in" &&
          knownCollection(context.sourceCode, node.right)
        )
          context.report({ node, messageId: "ambiguousCollectionIn" });
      },
    };
  },
});
