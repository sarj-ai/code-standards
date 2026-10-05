/**
 * @fileoverview prefer-nullish-filter-predicate — use an explicit nullish predicate for locally annotated collections.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-nullish-filter-predicate.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, SourceCode, Variable } from "@oxlint/plugins";
import { createRule, type RuleDocumentation } from "./_docs.js";
import {
  arrayMethodTarget,
  resolveArrayBinding,
  unwrapArrayExpression,
} from "./_array-method.js";
import { isGeneratedFile } from "./_paths.js";

export const PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION = {
  summary:
    "Use explicit nullish predicates when local array syntax proves Boolean removes only nullish values.",
  rationale:
    "An explicit predicate preserves the runtime values and lets TypeScript narrow null and undefined.",
  remediation: "Filter with value !== null && value !== undefined.",
  category: "correctness",
  autofix: "suggestion",
  limitations: [
    "Checks local array annotations with nullish and truthy literal or nonempty object-shape members, direct array literals and stable aliases. Boolean must be unshadowed.",
    "Imported types, local type aliases, inferred call results, generic/custom array types, primitive broad types, falsy members, reassigned bindings and literal arrays that mutate or escape are excluded. Object method replacement and global library augmentation are not tracked.",
  ],
  examples: [
    {
      id: "explicit-nullish-predicate",
      title: "Nullish filtering narrows the result",
      outcome: "no-match",
      files: [
        {
          path: "src/users.ts",
          source:
            "declare const users: readonly ({ id: string } | null)[]; const present = users.filter((user) => user !== null && user !== undefined);",
        },
      ],
      focusPath: "src/users.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "boolean-nullish-filter",
      title: "Boolean filtering loses nullish narrowing",
      outcome: "match",
      files: [
        {
          path: "src/users.ts",
          source:
            "declare const users: readonly ({ id: string } | null)[]; const present = users.filter(Boolean);",
        },
      ],
      focusPath: "src/users.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
/** Only infer from array literals that stay local and have no mutation or opaque escape. */
function locallyReadOnly(
  sourceCode: SourceCode,
  variable: Variable,
  visited = new Set<Variable>(),
): boolean {
  if (visited.has(variable)) return true;
  visited.add(variable);
  return variable.references.every((reference) => {
    if (reference.init) return true;
    const identifier = reference.identifier;
    const parent = identifier.parent;
    if (
      parent?.type === "VariableDeclarator" &&
      parent.init === identifier &&
      parent.id.type === "Identifier" &&
      parent.parent.type === "VariableDeclaration" &&
      parent.parent.kind === "const"
    ) {
      const alias = resolveArrayBinding(sourceCode, parent.id);
      return alias !== null && locallyReadOnly(sourceCode, alias, visited);
    }
    const member =
      parent?.type === "MemberExpression" ? arrayMethodTarget(parent) : null;
    return (
      member?.object === identifier &&
      member.name === "filter" &&
      parent?.parent?.type === "CallExpression" &&
      parent.parent.callee === parent
    );
  });
}

function knownNullishArray(
  sourceCode: SourceCode,
  node: ESTree.Node,
  visited = new Set<Variable>(),
): boolean {
  node = unwrapArrayExpression(node);
  if (node.type === "ArrayExpression") return nullishArrayLiteral(node);
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
    const annotation = identifier.typeAnnotation?.typeAnnotation;
    const element =
      annotation === undefined ? null : elementType(sourceCode, annotation);
    if (element !== null) return nullishTruthyType(element);
  }
  for (const definition of variable.defs) {
    if (
      definition.type === "Variable" &&
      definition.node.type === "VariableDeclarator" &&
      definition.node.parent.type === "VariableDeclaration" &&
      definition.node.parent.kind === "const" &&
      definition.node.init !== null
    )
      return (
        locallyReadOnly(sourceCode, variable) &&
        knownNullishArray(sourceCode, definition.node.init, visited)
      );
  }
  return false;
}
/** Array literals provide direct value evidence without resolving a binding. */
function nullishArrayLiteral(node: ESTree.ArrayExpression): boolean {
  let nullish = false;
  for (const element of node.elements) {
    if (element?.type === "Literal" && element.value === null) nullish = true;
    else if (
      element === null ||
      element.type === "SpreadElement" ||
      !(
        (element.type === "Literal" && !!element.value) ||
        element.type === "ObjectExpression" ||
        element.type === "ArrayExpression"
      )
    )
      return false;
  }
  return nullish;
}

function elementType(
  sourceCode: SourceCode,
  type: ESTree.TSType,
): ESTree.TSType | null {
  if (
    type.type === "TSParenthesizedType" ||
    (type.type === "TSTypeOperator" && type.operator === "readonly")
  )
    return elementType(sourceCode, type.typeAnnotation);
  if (type.type === "TSArrayType") return type.elementType;
  if (
    type.type === "TSTypeReference" &&
    type.typeName.type === "Identifier" &&
    ["Array", "ReadonlyArray"].includes(type.typeName.name) &&
    !resolveArrayBinding(sourceCode, type.typeName)?.defs.length
  )
    return type.typeArguments?.params[0] ?? null;
  return null;
}

function nullishTruthyType(type: ESTree.TSType): boolean {
  if (type.type === "TSParenthesizedType")
    return nullishTruthyType(type.typeAnnotation);
  if (type.type !== "TSUnionType") return false;
  let nullish = false;
  for (const member of type.types) {
    if (
      member.type === "TSNullKeyword" ||
      member.type === "TSUndefinedKeyword" ||
      (member.type === "TSLiteralType" &&
        member.literal.type === "Literal" &&
        member.literal.value === null)
    )
      nullish = true;
    else if (!truthyType(member)) return false;
  }
  return nullish;
}

function truthyType(type: ESTree.TSType): boolean {
  if (type.type === "TSParenthesizedType")
    return truthyType(type.typeAnnotation);
  if (type.type === "TSLiteralType") {
    const literal = type.literal;
    return literal.type === "Literal" && !!literal.value;
  }
  return (
    type.type === "TSSymbolKeyword" ||
    type.type === "TSFunctionType" ||
    (type.type === "TSTypeLiteral" &&
      type.members.length > 0 &&
      type.members.every((member) => member.type !== "TSIndexSignature"))
  );
}
export default createRule({
  name: "prefer-nullish-filter-predicate",
  documentation: PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description: PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION.summary,
    },
    schema: [],
    hasSuggestions: true,
    messages: {
      preferNullishPredicate:
        "This locally identified array contains only nullish or truthy values. Use an explicit nullish predicate to retain narrowing.",
      replaceBoolean: "Replace Boolean with an explicit nullish predicate.",
    },
  },
  defaultOptions: [],
  createOnce(context) {
    let generated = false;
    return {
      Program(): void {
        generated = isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text);
      },
      CallExpression(node): void {
        if (generated) return;
        const callback = node.arguments[0];
        const method = arrayMethodTarget(node.callee);
        if (
          node.arguments.length !== 1 ||
          callback?.type !== "Identifier" ||
          callback.name !== "Boolean" ||
          resolveArrayBinding(context.sourceCode, callback)?.defs.length ||
          method?.name !== "filter" ||
          !knownNullishArray(context.sourceCode, method.object)
        )
          return;
        context.report({
          node: callback,
          messageId: "preferNullishPredicate",
          suggest: [
            {
              messageId: "replaceBoolean",
              fix: (fixer) =>
                fixer.replaceText(
                  callback,
                  "(value) => value !== null && value !== undefined",
                ),
            },
          ],
        });
      },
    };
  },
});
