/**
 * @fileoverview no-json-stringify-object-equality — JSON serialization is not structural object equality.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-json-stringify-object-equality.test.ts
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  ESLintUtils,
  type ParserServicesWithTypeInformation,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";
import ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "serializedObjectEquality";
type Options = readonly [];

export const NO_JSON_STRINGIFY_OBJECT_EQUALITY_DOCUMENTATION = {
  summary: "Do not use JSON serialization as structural object equality.",
  rationale: "JSON text equality depends on property insertion order and serialization behavior, so semantically equal objects can compare unequal and distinct values can collapse together.",
  remediation: "Compare an explicit domain projection structurally, or use a reviewed canonical serializer when JSON semantics are required.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Only direct binary comparisons between two unshadowed JSON.stringify calls are checked.",
    "Primitive-only arrays are excluded when TypeScript can prove their element types.",
    "Aliases, stored serialization results, custom JSON objects, tests, generated files, and equality hidden inside helper calls are excluded.",
  ],
  examples: [
    {
      id: "domain-comparator",
      title: "Use an explicit structural comparator",
      outcome: "no-match",
      files: [{ path: "src/compare.ts", source: "const same = sameRecord(actual, expected);" }],
      focusPath: "src/compare.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "serialized-object-equality",
      title: "Do not compare object serialization",
      outcome: "match",
      files: [{ path: "src/compare.ts", source: "const same = JSON.stringify({ id: '1', state: 'ready' }) === JSON.stringify({ state: 'ready', id: '1' });" }],
      focusPath: "src/compare.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const EQUALITY_OPERATORS: ReadonlySet<string> = new Set(["!=", "!==", "==", "==="]);
const PRIMITIVE_FLAGS =
  ts.TypeFlags.BigIntLike |
  ts.TypeFlags.BooleanLike |
  ts.TypeFlags.ESSymbolLike |
  ts.TypeFlags.Never |
  ts.TypeFlags.Null |
  ts.TypeFlags.NumberLike |
  ts.TypeFlags.StringLike |
  ts.TypeFlags.Undefined |
  ts.TypeFlags.Void;

function unwrapExpression(node: TSESTree.Expression): TSESTree.Expression {
  let current = node;
  while (
    current.type === AST_NODE_TYPES.ChainExpression ||
    current.type === AST_NODE_TYPES.TSAsExpression ||
    current.type === AST_NODE_TYPES.TSNonNullExpression ||
    current.type === AST_NODE_TYPES.TSTypeAssertion
  ) {
    current = current.expression;
  }
  return current;
}

function jsonStringifyArgument(
  node: TSESTree.Expression,
  sourceCode: Readonly<TSESLint.SourceCode>,
): TSESTree.Expression | null {
  const expression = unwrapExpression(node);
  if (expression.type !== AST_NODE_TYPES.CallExpression) return null;
  const { callee } = expression;
  if (
    callee.type !== AST_NODE_TYPES.MemberExpression ||
    callee.computed ||
    callee.object.type !== AST_NODE_TYPES.Identifier ||
    callee.object.name !== "JSON" ||
    callee.property.type !== AST_NODE_TYPES.Identifier ||
    callee.property.name !== "stringify"
  ) {
    return null;
  }
  const variable = ASTUtils.findVariable(sourceCode.getScope(callee.object), "JSON");
  if (variable !== null && variable.defs.length > 0) return null;
  const argument = expression.arguments[0];
  return argument !== undefined && argument.type !== AST_NODE_TYPES.SpreadElement
    ? argument
    : null;
}

function typeMayContainObject(type: ts.Type, checker: ts.TypeChecker): boolean {
  if (type.isUnionOrIntersection()) {
    return type.types.some((member) => typeMayContainObject(member, checker));
  }
  if ((type.flags & PRIMITIVE_FLAGS) !== 0) return false;
  if ((type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.TypeParameter)) !== 0) {
    return true;
  }
  if (checker.isArrayType(type) || checker.isTupleType(type)) {
    const elements = checker.getTypeArguments(type as ts.TypeReference);
    return elements.some((element) => typeMayContainObject(element, checker));
  }
  const symbolName = type.getSymbol()?.getName();
  if ((symbolName === "Array" || symbolName === "ReadonlyArray") && (type.flags & ts.TypeFlags.Object) !== 0) {
    const elements = checker.getTypeArguments(type as ts.TypeReference);
    return elements.length === 0 || elements.some((element) => typeMayContainObject(element, checker));
  }
  return true;
}

function syntaxMayContainObject(node: TSESTree.Expression): boolean | null {
  const expression = unwrapExpression(node);
  if (expression.type === AST_NODE_TYPES.ObjectExpression) return true;
  if (expression.type !== AST_NODE_TYPES.ArrayExpression) return null;
  for (const element of expression.elements) {
    if (element === null) continue;
    if (element.type === AST_NODE_TYPES.SpreadElement) return null;
    if (
      element.type !== AST_NODE_TYPES.Literal &&
      !(element.type === AST_NODE_TYPES.TemplateLiteral && element.expressions.length === 0)
    ) {
      return true;
    }
  }
  return false;
}

export default createRule<Options, MessageIds>({
  name: "no-json-stringify-object-equality",
  documentation: NO_JSON_STRINGIFY_OBJECT_EQUALITY_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: "Do not use JSON serialization as structural object equality." },
    schema: [],
    messages: {
      serializedObjectEquality:
        "`JSON.stringify` compares serialization details, not object structure. Compare an explicit domain projection or use reviewed canonical serialization.",
    },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    if (
      isTestFile(context.filename) ||
      isGeneratedFile(context.filename, sourceCode.text)
    ) {
      return {};
    }
    let services: ParserServicesWithTypeInformation | null;
    try {
      services = ESLintUtils.getParserServices(context);
    } catch {
      services = null;
    }
    const checker = services?.program.getTypeChecker();

    function mayContainObject(node: TSESTree.Expression): boolean {
      const syntax = syntaxMayContainObject(node);
      if (syntax !== null) return syntax;
      if (services === null || checker === undefined) return false;
      const type = checker.getTypeAtLocation(
        services.esTreeNodeToTSNodeMap.get(node),
      );
      return typeMayContainObject(type, checker);
    }

    return {
      BinaryExpression(node): void {
        if (!EQUALITY_OPERATORS.has(node.operator)) return;
        if (node.left.type === AST_NODE_TYPES.PrivateIdentifier) return;
        const left = jsonStringifyArgument(node.left, sourceCode);
        const right = jsonStringifyArgument(node.right, sourceCode);
        if (left === null || right === null) return;
        if (!mayContainObject(left) && !mayContainObject(right)) return;
        context.report({ node, messageId: "serializedObjectEquality" });
      },
    };
  },
});
