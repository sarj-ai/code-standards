/**
 * @fileoverview prefer-non-nullable-collection — `T[] | null` gives an empty collection two representations and a null check to every caller.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-non-nullable-collection.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "preferNonNullableCollection";
type Options = readonly [];

const ARRAY_TYPE_NAMES: ReadonlySet<string> = new Set(["Array", "ReadonlyArray"]);

function propertyName(node: TSESTree.TSPropertySignature | TSESTree.PropertyDefinition): string {
  const key = node.key;
  if (key.type === AST_NODE_TYPES.Identifier) return key.name;
  if (key.type === AST_NODE_TYPES.Literal) return String(key.value);
  return "collection";
}

function isArrayType(node: TSESTree.TypeNode): boolean {
  if (node.type === AST_NODE_TYPES.TSArrayType) return true;
  return (
    node.type === AST_NODE_TYPES.TSTypeReference &&
    node.typeName.type === AST_NODE_TYPES.Identifier &&
    ARRAY_TYPE_NAMES.has(node.typeName.name)
  );
}

function isNullishType(node: TSESTree.TypeNode): boolean {
  return node.type === AST_NODE_TYPES.TSNullKeyword || node.type === AST_NODE_TYPES.TSUndefinedKeyword;
}

function isNullableArrayOnly(node: TSESTree.TSUnionType): boolean {
  const values = node.types.filter((member) => !isNullishType(member));
  return values.length > 0 && values.length < node.types.length && values.every(isArrayType);
}

export default createRule<Options, MessageIds>({
  name: "prefer-non-nullable-collection",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Require array types to use an empty array instead of explicit nullish unions with two equivalent empty states.",
    },
    schema: [],
    messages: {
      preferNonNullableCollection:
        "`{{name}}` is a nullable array, so nullish and `[]` represent the same empty collection. Use a non-null array and default omitted values to `[]`.",
    },
  },
  defaultOptions: [],
  create(context) {
    const normalizedFilename = context.filename.replaceAll("\\", "/");
    if (
      isTestFile(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.text) ||
      /\/(?:vendor|vendored)\//u.test(normalizedFilename)
    ) {
      return {};
    }

    function checkOptionalProperty(
      node: TSESTree.TSPropertySignature | TSESTree.PropertyDefinition,
    ): void {
      const annotation = node.typeAnnotation?.typeAnnotation;
      if (annotation === undefined) return;
      if (annotation.type !== AST_NODE_TYPES.TSUnionType || !isNullableArrayOnly(annotation)) {
        return;
      }
      context.report({
        node,
        messageId: "preferNonNullableCollection",
        data: { name: propertyName(node) },
      });
    }

    return {
      TSPropertySignature: checkOptionalProperty,
      PropertyDefinition: checkOptionalProperty,
      TSTypeAliasDeclaration(node): void {
        if (node.typeAnnotation.type !== AST_NODE_TYPES.TSUnionType) return;
        if (!isNullableArrayOnly(node.typeAnnotation)) return;
        context.report({
          node,
          messageId: "preferNonNullableCollection",
          data: { name: node.id.name },
        });
      },
    };
  },
});
