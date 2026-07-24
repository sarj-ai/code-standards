/**
 * @fileoverview Flag TanStack Router `validateSearch` implementations that
 * hand-roll "validation" with `as` casts. A cast asserts a shape without
 * checking it, so malformed query params flow into the app typed as clean
 * data. Use a schema validator (e.g. `zodValidator(searchSchema)` from
 * `@tanstack/zod-adapter`, or `searchSchema.parse`) so the search params are
 * actually validated at runtime.
 *
 * Deliberately narrow: only fires on a property literally named
 * `validateSearch` whose value is a function containing at least one
 * `as` cast (`as const` exempt — it narrows rather than lies).
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

type MessageIds = "castInValidateSearch";
type Options = readonly [];

function isConstAssertion(node: TSESTree.TSAsExpression): boolean {
  return (
    node.typeAnnotation.type === AST_NODE_TYPES.TSTypeReference &&
    node.typeAnnotation.typeName.type === AST_NODE_TYPES.Identifier &&
    node.typeAnnotation.typeName.name === "const"
  );
}

/** Depth-first search for the first non-`as const` TSAsExpression under `node`. */
function findAsExpression(node: TSESTree.Node): TSESTree.TSAsExpression | null {
  if (node.type === AST_NODE_TYPES.TSAsExpression && !isConstAssertion(node)) {
    return node;
  }
  for (const key of Object.keys(node)) {
    if (key === "parent") {
      continue;
    }
    const value = (node as unknown as Record<string, unknown>)[key];
    const children = Array.isArray(value) ? value : [value];
    for (const child of children) {
      if (
        child !== null &&
        typeof child === "object" &&
        "type" in child &&
        typeof (child as { type: unknown }).type === "string"
      ) {
        const found = findAsExpression(child as TSESTree.Node);
        if (found !== null) {
          return found;
        }
      }
    }
  }
  return null;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "require-schema-validate-search",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow `as` casts inside hand-rolled `validateSearch` functions; use a schema validator (e.g. zodValidator) so search params are validated at runtime.",
    },
    schema: [],
    messages: {
      castInValidateSearch:
        "This `validateSearch` asserts the search-param shape with `as` instead of validating it — malformed query params flow through typed as clean data. Use a schema validator (e.g. `zodValidator(searchSchema)` or `searchSchema.parse`) instead of casting.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      Property(node: TSESTree.Property): void {
        const isValidateSearchKey =
          (!node.computed &&
            node.key.type === AST_NODE_TYPES.Identifier &&
            node.key.name === "validateSearch") ||
          (node.key.type === AST_NODE_TYPES.Literal &&
            node.key.value === "validateSearch");
        if (!isValidateSearchKey) {
          return;
        }

        if (
          node.value.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
          node.value.type !== AST_NODE_TYPES.FunctionExpression
        ) {
          return;
        }

        const cast = findAsExpression(node.value.body);
        if (cast !== null) {
          context.report({ node: cast, messageId: "castInValidateSearch" });
        }
      },
    };
  },
});
