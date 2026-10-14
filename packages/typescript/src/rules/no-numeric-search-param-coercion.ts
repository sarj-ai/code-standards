/**
 * @fileoverview no-numeric-search-param-coercion — numeric URL search parameters are parsed by a schema, not coerced.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-numeric-search-param-coercion.test.ts
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  ESLintUtils,
  type ParserServicesWithTypeInformation,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { unwrapExpression } from "./_unwrap-expression.js";

type MessageIds = "noNumericSearchParamCoercion";
type Options = readonly [];

const GLOBAL_PARSERS: ReadonlySet<string> = new Set(["parseInt", "parseFloat", "Number"]);
const NUMBER_PARSERS: ReadonlySet<string> = new Set(["parseInt", "parseFloat"]);
const SEARCH_PARAM_TYPES: ReadonlySet<string> = new Set(["URLSearchParams", "ReadonlyURLSearchParams"]);

export const NO_NUMERIC_SEARCH_PARAM_COERCION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Parse numeric URL search parameters with a schema instead of parseInt or Number.",
  rationale:
    "parseInt, parseFloat and Number accept a missing or malformed query value and return NaN or a truncated number (`parseInt(\"10abc\")` is 10), which then reaches queries and pagination unchecked.",
  remediation:
    "Parse the value with a schema that states the contract, for example `z.coerce.number().int().positive().default(10).parse(params.get(\"page\") ?? undefined)`.",
  category: "correctness",
  limitations: [
    "Requires type information: only the `get` result of a value typed as URLSearchParams or ReadonlyURLSearchParams is recognized.",
    "Search parameter objects passed as page props, values copied into other variables, and unary `+` coercion are not followed.",
  ],
  examples: [
    {
      id: "schema-parsed-page",
      title: "Parse the page number with a schema",
      outcome: "no-match",
      files: [{
        path: "src/page.ts",
        source:
          "declare const z: { coerce: { number(): { parse(value: unknown): number } } };\n" +
          "export function page(params: URLSearchParams): number {\n  return z.coerce.number().parse(params.get(\"page\") ?? undefined);\n}\n",
      }],
      focusPath: "src/page.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "parse-int-page",
      title: "Do not coerce a search parameter with parseInt",
      outcome: "match",
      files: [{
        path: "src/page.ts",
        source: "export function page(params: URLSearchParams): number {\n  return parseInt(params.get(\"page\") ?? \"1\", 10);\n}\n",
      }],
      focusPath: "src/page.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "no-numeric-search-param-coercion",
  documentation: NO_NUMERIC_SEARCH_PARAM_COERCION_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_NUMERIC_SEARCH_PARAM_COERCION_DOCUMENTATION.summary },
    schema: [],
    messages: {
      noNumericSearchParamCoercion:
        "This coerces a URL search parameter with {{parser}}, which turns missing or malformed input into NaN or a truncated number. Parse it with a schema such as z.coerce.number().int().",
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
    const typed = services;
    return {
      CallExpression(node): void {
        const [first] = node.arguments;
        if (first === undefined || !isNumericParser(context.sourceCode, node.callee)) return;
        const call = searchParamGetCall(first);
        if (call === null || !isSearchParamReceiver(call, typed)) return;
        context.report({
          node,
          messageId: "noNumericSearchParamCoercion",
          data: { parser: context.sourceCode.getText(node.callee) },
        });
      },
    };
  },
});

function isNumericParser(
  sourceCode: Readonly<TSESLint.SourceCode>,
  callee: TSESTree.Expression,
): boolean {
  if (callee.type === AST_NODE_TYPES.Identifier) {
    return GLOBAL_PARSERS.has(callee.name) && isUnshadowedGlobal(sourceCode, callee);
  }
  return (
    callee.type === AST_NODE_TYPES.MemberExpression &&
    !callee.computed &&
    callee.object.type === AST_NODE_TYPES.Identifier &&
    callee.object.name === "Number" &&
    callee.property.type === AST_NODE_TYPES.Identifier &&
    NUMBER_PARSERS.has(callee.property.name) &&
    isUnshadowedGlobal(sourceCode, callee.object)
  );
}

function isUnshadowedGlobal(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.Identifier,
): boolean {
  const variable = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
  return variable === null || variable.defs.length === 0;
}

function searchParamGetCall(argument: TSESTree.CallExpressionArgument): TSESTree.CallExpression | null {
  let value: TSESTree.Node = unwrapExpression(argument);
  if (value.type === AST_NODE_TYPES.AwaitExpression) value = unwrapExpression(value.argument);
  if (value.type === AST_NODE_TYPES.LogicalExpression && value.operator === "??") value = unwrapExpression(value.left);
  if (value.type === AST_NODE_TYPES.ChainExpression) value = value.expression;
  if (
    value.type !== AST_NODE_TYPES.CallExpression ||
    value.callee.type !== AST_NODE_TYPES.MemberExpression ||
    value.callee.computed ||
    value.callee.property.type !== AST_NODE_TYPES.Identifier ||
    value.callee.property.name !== "get"
  ) {
    return null;
  }
  return value;
}

function isSearchParamReceiver(
  call: TSESTree.CallExpression,
  services: ParserServicesWithTypeInformation,
): boolean {
  if (call.callee.type !== AST_NODE_TYPES.MemberExpression) return false;
  const checker = services.program.getTypeChecker();
  const type = checker.getNonNullableType(
    checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(call.callee.object)),
  );
  const symbol = type.getSymbol() ?? type.aliasSymbol;
  return symbol !== undefined && SEARCH_PARAM_TYPES.has(symbol.name);
}
