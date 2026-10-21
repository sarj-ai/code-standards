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

import { unwrapExpression } from "./_unwrap-expression.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "serializedObjectEquality";
type Options = readonly [];

export const NO_JSON_STRINGIFY_OBJECT_EQUALITY_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Do not use JSON serialization as structural object equality.",
  rationale: "JSON text equality depends on property insertion order and serialization behavior, so semantically equal objects can compare unequal and distinct values can collapse together.",
  remediation: "Compare an explicit domain projection structurally, or use a reviewed canonical serializer when JSON semantics are required.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Only direct binary comparisons between two unshadowed global JSON.stringify calls, including stable const destructured aliases of that global, are checked.",
    "Primitive-only arrays are excluded when TypeScript can prove their element types.",
    "Mutable, defaulted, reassigned, transitive and unknown aliases, stored serialization results, custom JSON objects, tests, generated files, and equality hidden inside helper calls are excluded.",
  ],
  examples: [
    {
      id: "domain-comparator",
      title: "Use an explicit structural comparator",
      outcome: "no-match",
      files: [{ path: "src/compare.ts", source: "type RecordState = { id: string; state: string };\nfunction sameRecord(actual: RecordState, expected: RecordState): boolean { return actual.id === expected.id && actual.state === expected.state; }\nconst same = sameRecord({ id: '1', state: 'ready' }, { state: 'ready', id: '1' });" }],
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

function unwrapComparisonExpression(node: TSESTree.Expression): TSESTree.Expression {
  let current = unwrapExpression(node);
  while (current.type === AST_NODE_TYPES.ChainExpression) {
    current = unwrapExpression(current.expression);
  }
  return current;
}

function jsonStringifyArgument(
  node: TSESTree.Expression,
  sourceCode: Readonly<TSESLint.SourceCode>,
): TSESTree.Expression | null {
  const expression = unwrapComparisonExpression(node);
  if (expression.type !== AST_NODE_TYPES.CallExpression) return null;
  if (expression.callee.type === AST_NODE_TYPES.Super || !isJsonStringify(expression.callee, sourceCode)) return null;
  const argument = expression.arguments[0];
  return argument !== undefined && argument.type !== AST_NODE_TYPES.SpreadElement
    ? argument
    : null;
}

function isJsonStringify(
  node: TSESTree.Expression,
  sourceCode: Readonly<TSESLint.SourceCode>,
): boolean {
  const expression = unwrapComparisonExpression(node);
  if (expression.type === AST_NODE_TYPES.MemberExpression) {
    return ASTUtils.getPropertyName(expression) === "stringify" &&
      expression.object.type !== AST_NODE_TYPES.Super && isGlobalJson(expression.object, sourceCode);
  }
  if (expression.type !== AST_NODE_TYPES.Identifier) return false;
  const binding = ASTUtils.findVariable(sourceCode.getScope(expression), expression.name);
  if (binding === null || binding.defs.length !== 1 ||
    binding.references.some(reference => reference.isWrite() && reference.init !== true)) return false;
  const [definition] = binding.defs;
  if (definition?.type !== "Variable" || definition.parent.kind !== "const" ||
    definition.node.id.type !== AST_NODE_TYPES.ObjectPattern ||
    definition.node.init === null || !isGlobalJson(definition.node.init, sourceCode)) return false;
  return definition.node.id.properties.some(property =>
    property.type === AST_NODE_TYPES.Property && ASTUtils.getPropertyName(property) === "stringify" &&
    property.value.type === AST_NODE_TYPES.Identifier &&
    ASTUtils.findVariable(sourceCode.getScope(property.value), property.value.name) === binding);
}

function isGlobalJson(
  node: TSESTree.Expression,
  sourceCode: Readonly<TSESLint.SourceCode>,
): boolean {
  const expression = unwrapComparisonExpression(node);
  if (expression.type !== AST_NODE_TYPES.Identifier || expression.name !== "JSON") return false;
  const binding = ASTUtils.findVariable(sourceCode.getScope(expression), expression.name);
  return binding === null || binding.defs.length === 0;
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
  const expression = unwrapComparisonExpression(node);
  if (expression.type === AST_NODE_TYPES.ObjectExpression) return true;
  if (expression.type === AST_NODE_TYPES.Literal) return "regex" in expression;
  if (expression.type === AST_NODE_TYPES.TemplateLiteral || expression.type === AST_NODE_TYPES.UnaryExpression) return false;
  if (expression.type !== AST_NODE_TYPES.ArrayExpression) return null;
  let unknown = false;
  for (const element of expression.elements) {
    if (element === null) continue;
    const result = element.type === AST_NODE_TYPES.SpreadElement ? null : syntaxMayContainObject(element);
    if (result === true) return true;
    if (result === null) unknown = true;
  }
  return unknown ? null : false;
}

function untypedArrayMayContainObject(node: TSESTree.ArrayExpression): boolean {
  return node.elements.some(element => {
    if (element === null || element.type === AST_NODE_TYPES.SpreadElement) return false;
    const value = unwrapComparisonExpression(element);
    return value.type === AST_NODE_TYPES.ArrayExpression
      ? untypedArrayMayContainObject(value)
      : syntaxMayContainObject(value) !== false;
  });
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
      isTestFile(context) ||
      isGeneratedFile(context, sourceCode.text)
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
      if (services === null || checker === undefined) {
        const expression = unwrapComparisonExpression(node);
        return expression.type === AST_NODE_TYPES.ArrayExpression && untypedArrayMayContainObject(expression);
      }
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
