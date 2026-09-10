/**
 * @fileoverview no-in-operator-on-built-in-collections — distinguish collection membership from object property lookup.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-in-operator-on-built-in-collections.test.ts
 */

import {
  ESLintUtils,
  type ParserServicesWithTypeInformation,
  type TSESTree,
} from "@typescript-eslint/utils";
import * as ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "ambiguousCollectionIn";
type Options = readonly [];

const COLLECTION_NAMES: ReadonlySet<string> = new Set([
  "Map",
  "ReadonlyMap",
  "WeakMap",
  "Set",
  "ReadonlySet",
  "WeakSet",
]);

export const NO_IN_OPERATOR_ON_BUILT_IN_COLLECTIONS_DOCUMENTATION = {
  summary: "Do not use the `in` operator to test entries in built-in Map and Set collections.",
  rationale:
    "The `in` operator checks properties on the collection object and its prototype, while `.has()` checks stored entries. The similar spelling can silently test the wrong namespace.",
  remediation:
    "Use `collection.has(key)` for entry membership. Use `Reflect.has(collection, property)` when prototype-aware property lookup or Proxy `has` behavior is intentional.",
  category: "correctness",
  since: "15.17.14",
  autofix: "none",
  limitations: [
    "The receiver type must resolve directly to a default-library Map, ReadonlyMap, WeakMap, Set, ReadonlySet, or WeakSet declaration; type aliases, unions, intersections, type parameters, subclasses, structural lookalikes, any, unknown, and generated files are excluded.",
    "TypeScript cannot prove runtime Proxy wrapping or prototype mutation, so the diagnostic offers Reflect.has as the semantics-preserving property-check alternative and never autofixes to .has().",
    "Plain objects, arrays, TypeScript object-shape narrowing, private-brand checks, and for-in statements are not checked.",
  ],
  examples: [
    {
      id: "map-entry-membership",
      title: "Use Map.has for entry membership",
      outcome: "match",
      files: [{
        path: "src/cache.ts",
        source: "declare const cache: Map<string, object>; declare const key: string; if (key in cache) use(cache);",
      }],
      focusPath: "src/cache.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "object-property-narrowing",
      title: "Preserve ordinary object property narrowing",
      outcome: "no-match",
      files: [{
        path: "src/cache.ts",
        source: "declare const value: { id: string } | { slug: string }; if ('id' in value) use(value.id);",
      }],
      focusPath: "src/cache.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function isDefaultLibraryCollection(
  node: TSESTree.Expression,
  services: ParserServicesWithTypeInformation,
): boolean {
  const checker = services.program.getTypeChecker();
  const tsNode = services.esTreeNodeToTSNodeMap.get(node);
  const type = checker.getTypeAtLocation(tsNode);
  if (
    (type.flags &
      (ts.TypeFlags.Any |
        ts.TypeFlags.Unknown |
        ts.TypeFlags.Never |
        ts.TypeFlags.TypeParameter |
        ts.TypeFlags.Union |
        ts.TypeFlags.Intersection)) !==
    0
  ) {
    return false;
  }
  return isDefaultLibraryCollectionSymbol(type.getSymbol(), services);
}

function isDefaultLibraryCollectionSymbol(
  symbol: ts.Symbol | undefined,
  services: ParserServicesWithTypeInformation,
): boolean {
  if (symbol === undefined || !COLLECTION_NAMES.has(symbol.name)) return false;
  const declarations = symbol.declarations ?? [];
  return (
    declarations.length > 0 &&
    declarations.every((declaration) =>
      services.program.isSourceFileDefaultLibrary(declaration.getSourceFile())) &&
    declarations.some(
      (declaration) =>
        ts.isInterfaceDeclaration(declaration) && declaration.name.text === symbol.name,
    )
  );
}

export default createRule<Options, MessageIds>({
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
        "`in` checks properties on this collection object, not stored entries. Use `.has()` for entry membership or `Reflect.has()` for intentional property lookup.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    let services: ParserServicesWithTypeInformation | null;
    try {
      services = ESLintUtils.getParserServices(context);
    } catch {
      services = null;
    }
    if (services === null) return {};
    return {
      BinaryExpression(node): void {
        if (
          node.operator !== "in" ||
          !isDefaultLibraryCollection(node.right, services)
        ) {
          return;
        }
        context.report({ node, messageId: "ambiguousCollectionIn" });
      },
    };
  },
});
