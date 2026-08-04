/**
 * @fileoverview require-static-next-matcher — Next.js matcher configuration must be statically analyzable at build time.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/require-static-next-matcher.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";

type MessageIds = "dynamicMatcher";
type Options = readonly [];

const NEXT_ENTRY_FILE = /(?:^|[/\\])(?:middleware|proxy)\.[cm]?[jt]sx?$/u;

function unwrapExpression(node: TSESTree.Node): TSESTree.Node {
  if (
    node.type === AST_NODE_TYPES.TSAsExpression ||
    node.type === AST_NODE_TYPES.TSSatisfiesExpression ||
    node.type === AST_NODE_TYPES.TSNonNullExpression ||
    node.type === AST_NODE_TYPES.TSTypeAssertion
  ) {
    return unwrapExpression(node.expression);
  }
  return node;
}

function isStaticValue(node: TSESTree.Node): boolean {
  const value = unwrapExpression(node);
  if (value.type === AST_NODE_TYPES.Literal) {
    return true;
  }
  if (value.type === AST_NODE_TYPES.TemplateLiteral) {
    return value.expressions.length === 0;
  }
  if (value.type === AST_NODE_TYPES.ArrayExpression) {
    return value.elements.every(
      (element) =>
        element !== null &&
        element.type !== AST_NODE_TYPES.SpreadElement &&
        isStaticValue(element),
    );
  }
  if (value.type === AST_NODE_TYPES.ObjectExpression) {
    return value.properties.every(
      (property) =>
        property.type === AST_NODE_TYPES.Property &&
        property.kind === "init" &&
        !property.computed &&
        property.value.type !== AST_NODE_TYPES.AssignmentPattern &&
        isStaticValue(property.value),
    );
  }
  return false;
}

function propertyName(property: TSESTree.Property): string | null {
  if (property.computed) return null;
  if (property.key.type === AST_NODE_TYPES.Identifier) return property.key.name;
  return typeof property.key.value === "string" ? property.key.value : null;
}

export default createRule<Options, MessageIds>({
  name: "require-static-next-matcher",
  meta: {
    type: "problem",
    docs: {
      description:
        "Require Next.js middleware and proxy matcher configuration to contain only build-time literals.",
    },
    schema: [],
    messages: {
      dynamicMatcher:
        "Next.js matcher values must contain only literal arrays and objects. Calls, identifiers, concatenation, interpolated templates, and spreads are not statically analyzable and fail the production build.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (!NEXT_ENTRY_FILE.test(context.filename)) {
      return {};
    }

    return {
      ExportNamedDeclaration(node): void {
        if (node.declaration?.type !== AST_NODE_TYPES.VariableDeclaration) {
          return;
        }
        for (const declaration of node.declaration.declarations) {
          if (
            declaration.id.type !== AST_NODE_TYPES.Identifier ||
            declaration.id.name !== "config" ||
            declaration.init === null
          ) {
            continue;
          }
          const config = unwrapExpression(declaration.init);
          if (config.type !== AST_NODE_TYPES.ObjectExpression) {
            continue;
          }
          for (const property of config.properties) {
            if (
              property.type !== AST_NODE_TYPES.Property ||
              propertyName(property) !== "matcher" ||
              property.value.type === AST_NODE_TYPES.AssignmentPattern
            ) {
              continue;
            }
            if (!isStaticValue(property.value)) {
              context.report({ node: property.value, messageId: "dynamicMatcher" });
            }
          }
        }
      },
    };
  },
});
