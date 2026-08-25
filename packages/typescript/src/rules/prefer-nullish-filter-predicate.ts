/**
 * @fileoverview prefer-nullish-filter-predicate — `filter(Boolean)` does not narrow a nullish union even when every retained value is provably truthy.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-nullish-filter-predicate.test.ts
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  ESLintUtils,
  type ParserServicesWithTypeInformation,
  type TSESTree,
  type TSESLint,
} from "@typescript-eslint/utils";
import ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "preferNullishPredicate" | "replaceBoolean";
type Options = readonly [];

export const PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION = {
  summary:
    "Prefer an explicit nullish predicate when `filter(Boolean)` removes only nullish values but does not narrow the result type.",
  rationale:
    "An explicit nullish predicate preserves the same runtime elements while letting TypeScript remove `null` and `undefined` from the result.",
  remediation:
    "Replace `filter(Boolean)` with `filter((value) => value !== null && value !== undefined)`.",
  category: "correctness",
  autofix: "suggestion",
  limitations: [
    "The receiver must resolve to the built-in Array or ReadonlyArray filter method.",
    "Broad primitive types, falsy literals, any, unknown, generics, intersections, custom filters, and shadowed Boolean bindings are excluded.",
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
            "declare const users: readonly ({ id: string } | null)[];\nconst present = users.filter((user) => user !== null && user !== undefined);",
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
          source: "declare const users: readonly ({ id: string } | null)[];\nconst present = users.filter(Boolean);",
        },
      ],
      focusPath: "src/users.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function isUnshadowedBoolean(
  node: TSESTree.Identifier,
  context: TSESLint.RuleContext<MessageIds, Options>,
): boolean {
  const variable = ASTUtils.findVariable(context.sourceCode.getScope(node), node.name);
  return variable === null || variable.defs.length === 0;
}

function isBuiltinArrayFilter(
  node: TSESTree.MemberExpression,
  services: ParserServicesWithTypeInformation,
): boolean {
  const checker = services.program.getTypeChecker();
  const property = services.esTreeNodeToTSNodeMap.get(node.property);
  const symbol = checker.getSymbolAtLocation(property);
  return symbol?.declarations?.some((declaration) => {
    const owner = declaration.parent;
    return (
      ts.isInterfaceDeclaration(owner) &&
      (owner.name.text === "Array" || owner.name.text === "ReadonlyArray") &&
      services.program.isSourceFileDefaultLibrary(owner.getSourceFile())
    );
  }) ?? false;
}

function arrayElementType(
  node: TSESTree.Expression,
  services: ParserServicesWithTypeInformation,
): ts.Type | null {
  const checker = services.program.getTypeChecker();
  const receiver = services.esTreeNodeToTSNodeMap.get(node);
  return checker.getIndexTypeOfType(checker.getTypeAtLocation(receiver), ts.IndexKind.Number) ?? null;
}

const NULLISH_FLAGS = ts.TypeFlags.Null | ts.TypeFlags.Undefined;
const UNKNOWN_FLAGS =
  ts.TypeFlags.Any |
  ts.TypeFlags.Unknown |
  ts.TypeFlags.TypeParameter |
  ts.TypeFlags.Intersection |
  ts.TypeFlags.Enum |
  ts.TypeFlags.EnumLiteral;

function isNullishPlusTruthy(type: ts.Type, checker: ts.TypeChecker): boolean {
  const members = type.isUnion() ? type.types : [type];
  let sawNullish = false;
  for (const member of members) {
    if ((member.flags & NULLISH_FLAGS) !== 0) {
      sawNullish = true;
    } else if ((member.flags & ts.TypeFlags.Never) === 0 && !isProvablyTruthy(member, checker)) {
      return false;
    }
  }
  return sawNullish;
}

function isProvablyTruthy(type: ts.Type, checker: ts.TypeChecker): boolean {
  if ((type.flags & UNKNOWN_FLAGS) !== 0) return false;
  if ((type.flags & ts.TypeFlags.Object) !== 0) {
    return ![
      checker.getStringType(),
      checker.getNumberType(),
      checker.getBigIntType(),
      checker.getBooleanType(),
    ].some((primitive) => checker.isTypeAssignableTo(primitive, type));
  }
  if ((type.flags & (ts.TypeFlags.ESSymbol | ts.TypeFlags.UniqueESSymbol)) !== 0) return true;
  if ((type.flags & ts.TypeFlags.BooleanLiteral) !== 0) {
    return (type as ts.Type & { readonly intrinsicName?: string }).intrinsicName === "true";
  }
  if ((type.flags & ts.TypeFlags.StringLiteral) !== 0) {
    return (type as ts.StringLiteralType).value.length > 0;
  }
  if ((type.flags & ts.TypeFlags.NumberLiteral) !== 0) {
    const value = (type as ts.NumberLiteralType).value;
    return value !== 0 && !Number.isNaN(value);
  }
  if ((type.flags & ts.TypeFlags.BigIntLiteral) !== 0) {
    return (type as ts.BigIntLiteralType).value.base10Value !== "0";
  }
  return false;
}

function availableParameterName(
  node: TSESTree.CallExpression,
  context: TSESLint.RuleContext<MessageIds, Options>,
): string | null {
  for (const name of ["value", "item", "element", "candidate"] as const) {
    if (ASTUtils.findVariable(context.sourceCode.getScope(node), name) === null) return name;
  }
  return null;
}

export default createRule<Options, MessageIds>({
  name: "prefer-nullish-filter-predicate",
  documentation: PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION.summary },
    hasSuggestions: true,
    schema: [],
    messages: {
      preferNullishPredicate:
        "This built-in array contains only nullish or provably truthy values, so `filter(Boolean)` preserves runtime values but loses nullish narrowing. Use an explicit nullish predicate.",
      replaceBoolean: "Replace `Boolean` with an explicit nullish predicate.",
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
      CallExpression(node): void {
        const callee = node.callee;
        const callback = node.arguments[0];
        if (
          node.arguments.length !== 1 ||
          callback?.type !== AST_NODE_TYPES.Identifier ||
          callback.name !== "Boolean" ||
          callee.type !== AST_NODE_TYPES.MemberExpression ||
          callee.computed ||
          callee.property.type !== AST_NODE_TYPES.Identifier ||
          callee.property.name !== "filter" ||
          !isUnshadowedBoolean(callback, context) ||
          !isBuiltinArrayFilter(callee, services)
        ) return;
        const elementType = arrayElementType(callee.object, services);
        const checker = services.program.getTypeChecker();
        if (elementType === null || !isNullishPlusTruthy(elementType, checker)) return;
        const parameter = availableParameterName(node, context);
        context.report({
          node: callback,
          messageId: "preferNullishPredicate",
          suggest: parameter === null
            ? null
            : [{
                messageId: "replaceBoolean",
                fix: (fixer) => fixer.replaceText(
                  callback,
                  `(${parameter}) => ${parameter} !== null && ${parameter} !== undefined`,
                ),
              }],
        });
      },
    };
  },
});
