/**
 * @fileoverview Prefer non-null arrays in declared TypeScript data shapes.
 *
 * An array type such as `OrganizationId[] | null` gives an empty collection two
 * representations: nullish and `[]`. Requiring an array removes null checks
 * from the call chain and makes the project-wide contract explicit.
 *
 * The rule checks declared data shapes: interface/class properties, properties
 * in object type aliases, and direct array type aliases. An optional property
 * (`items?: T[]`) does not fire unless its written type also explicitly includes
 * `null` or `undefined`: omission is API input syntax, not a nullable collection
 * value. Mixed scalar-or-array unions do not fire because they model more than
 * an empty collection. Function-local annotations, tests, and generated
 * declarations are exempt.
 *
 * This is an opinionated application convention, not a TypeScript type-system
 * fact. When null is a meaningful third state (for example React Router uses
 * `matches: Match[] | null` to distinguish "no match" from an empty match set),
 * retain the union with an inline ESLint disable and its reason.
 *
 * Corpus sweep (2026-07-27): FastAPI, Pydantic, SQLModel, Zod, and React Router;
 * 2,901 Python/TypeScript files total. The final TypeScript rule reported 13
 * explicit nullable-array declarations. Every match had the advertised AST
 * shape; optional-only properties, tests, generated files, and vendor code
 * produced no reports.
 *
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

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

export default ESLintUtils.RuleCreator(
  (name) => `https://github.com/sarj-ai/standards/tree/main/packages/typescript#${name}`,
)<Options, MessageIds>({
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
