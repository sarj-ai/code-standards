/**
 * @fileoverview no-contradictory-type-predicate — primitive type guards must agree with both narrowing branches.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-contradictory-type-predicate.test.ts
 */
import { ASTUtils, AST_NODE_TYPES, ESLintUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { hasSeparatePredicateContract } from "./_has-separate-predicate-contract.js";
import { isGeneratedFile } from "./_paths.js";
import { staticString } from "./_static-string.js";
import { unwrapExpression } from "./_unwrap-expression.js";

type Options = readonly [];
type MessageIds = "contradictoryPredicate";
type FunctionNode = TSESTree.ArrowFunctionExpression | TSESTree.FunctionDeclaration | TSESTree.FunctionExpression;
type RuntimeKind = "string" | "number" | "bigint" | "boolean" | "symbol" | "undefined" | "object" | "function";

const RUNTIME_KINDS: ReadonlySet<string> = new Set(["string", "number", "bigint", "boolean", "symbol", "undefined", "object", "function"]);
const PRIMITIVE_KINDS: readonly (readonly [ts.TypeFlags, RuntimeKind])[] = [
  [ts.TypeFlags.String, "string"], [ts.TypeFlags.Number, "number"], [ts.TypeFlags.BigInt, "bigint"],
  [ts.TypeFlags.ESSymbol, "symbol"], [ts.TypeFlags.Undefined, "undefined"],
];

interface TypeofCheck {
  readonly parameter: TSESTree.Identifier;
  readonly kind: RuntimeKind;
}

export const NO_CONTRADICTORY_TYPE_PREDICATE_DOCUMENTATION = {
  summary: "Keep explicit primitive type predicates consistent with the typeof check they return.",
  rationale: "TypeScript trusts an explicit type predicate without verifying its implementation. A contradictory check admits the wrong primitive in the true branch or removes valid primitive alternatives from the false branch.",
  remediation: "Match the predicate to every primitive the check accepts and rejects, or use a boolean return for an intentionally partial check. Prefer compiler-inferred predicates when inference preserves the required contract.",
  category: "correctness",
  defaultLevel: "warning",
  autofix: "none",
  limitations: [
    "Requires type information, an explicit predicate over a directly named parameter and a single returned positive typeof equality for the same scope-resolved parameter. Both strict and loose equality and reversed operands are supported.",
    "Predicate targets must consist of broad primitive types (including complete boolean), and inputs must be unknown or a fully classified primitive/nullish union. Literal, branded, structural, generic, asserted, declaration-only and multi-statement validators are excluded rather than guessed. Overloaded implementations, contextually typed callbacks and methods with class heritage or contextual object contracts are preserved because they can have a separate callable domain.",
    "Compiler-invalid predicate target/input relations and typeof comparisons impossible for the input remain with existing compiler and unnecessary-condition controls. This rule does not validate arbitrary predicates or runtime refinements. Generated files are excluded; tests remain checked.",
  ],
  references: ["https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-5.html#inferred-type-predicates"],
  examples: [
    { id: "consistent-primitive-predicate", title: "Agree with the checked primitive", outcome: "no-match", files: [{ path: "src/guard.ts", source: 'function isText(value: unknown): value is string { return typeof value === "string"; }' }], focusPath: "src/guard.ts", expectedCount: 0, public: true },
    { id: "contradictory-primitive-predicate", title: "Do not promise a different primitive", outcome: "match", files: [{ path: "src/guard.ts", source: 'function isText(value: unknown): value is string { return typeof value === "number"; }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "no-contradictory-type-predicate",
  documentation: NO_CONTRADICTORY_TYPE_PREDICATE_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_CONTRADICTORY_TYPE_PREDICATE_DOCUMENTATION.summary },
    schema: [],
    messages: { contradictoryPredicate: "This predicate promises `{{promised}}`, but its typeof check recognizes only `{{checked}}`. Align both true and false branch narrowing with the check, or return boolean for a partial check." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text) || !context.sourceCode.parserServices?.program) return {};
    const services = ESLintUtils.getParserServices(context);
    const checker = services.program.getTypeChecker();

    function inspect(node: FunctionNode): void {
      const annotation = node.returnType?.typeAnnotation;
      if (node.async || node.generator || node.typeParameters !== undefined || annotation?.type !== AST_NODE_TYPES.TSTypePredicate ||
        annotation.asserts || annotation.parameterName.type !== AST_NODE_TYPES.Identifier || annotation.typeAnnotation === undefined) return;
      const name = annotation.parameterName.name;
      if (hasSeparatePredicateContract(services.esTreeNodeToTSNodeMap.get(node), checker)) return;
      const parameter = node.params.find((candidate): candidate is TSESTree.Identifier => candidate.type === AST_NODE_TYPES.Identifier && candidate.name === name);
      const expression = singleReturn(node);
      if (parameter?.typeAnnotation === undefined || expression === undefined) return;
      const check = typeofCheck(expression);
      if (check === undefined || !sameParameter(parameter, check.parameter, context.sourceCode)) return;
      const input = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(check.parameter));
      const target = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(annotation.typeAnnotation.typeAnnotation));
      if (!checker.isTypeAssignableTo(target, input)) return;
      const promised = primitiveKinds(target, checker, false);
      const possible = inputKinds(input, checker);
      if (promised === undefined || possible === undefined || !possible.has(check.kind)) return;
      const acceptsWrongKind = !promised.has(check.kind);
      const rejectsPromisedKind = [...promised].some((kind) => kind !== check.kind && possible.has(kind));
      if (!acceptsWrongKind && !rejectsPromisedKind) return;
      context.report({ node: annotation, messageId: "contradictoryPredicate", data: {
        promised: checker.typeToString(target), checked: check.kind,
      } });
    }

    return { FunctionDeclaration: inspect, FunctionExpression: inspect, ArrowFunctionExpression: inspect };
  },
});

function singleReturn(node: FunctionNode): TSESTree.Expression | undefined {
  if (node.body === undefined) return undefined;
  if (node.body.type !== AST_NODE_TYPES.BlockStatement) return node.body;
  const statement = node.body.body[0];
  return node.body.body.length === 1 && statement?.type === AST_NODE_TYPES.ReturnStatement && statement.argument !== null ? statement.argument : undefined;
}

function typeofCheck(expression: TSESTree.Expression): TypeofCheck | undefined {
  const value = unwrapExpression(expression);
  if (value.type !== AST_NODE_TYPES.BinaryExpression || (value.operator !== "===" && value.operator !== "==")) return undefined;
  for (const [tested, expected] of [[value.left, value.right], [value.right, value.left]] as const) {
    const operand = unwrapExpression(tested);
    const kind = staticString(expected);
    if (operand.type !== AST_NODE_TYPES.UnaryExpression || operand.operator !== "typeof" ||
      operand.argument.type !== AST_NODE_TYPES.Identifier || kind === null || !isRuntimeKind(kind)) continue;
    return { parameter: operand.argument, kind };
  }
  return undefined;
}

function isRuntimeKind(value: string): value is RuntimeKind {
  return RUNTIME_KINDS.has(value);
}

function sameParameter(declared: TSESTree.Identifier, tested: TSESTree.Identifier, sourceCode: TSESLint.SourceCode): boolean {
  const parameter = ASTUtils.findVariable(sourceCode.getScope(declared), declared.name);
  return parameter !== null && parameter === ASTUtils.findVariable(sourceCode.getScope(tested), tested.name);
}

function inputKinds(type: ts.Type, checker: ts.TypeChecker): ReadonlySet<RuntimeKind> | undefined {
  if ((type.flags & ts.TypeFlags.Unknown) !== 0) return new Set<RuntimeKind>(["string", "number", "bigint", "boolean", "symbol", "undefined", "object", "function"]);
  return primitiveKinds(type, checker, true);
}

function primitiveKinds(type: ts.Type, checker: ts.TypeChecker, allowLiterals: boolean): ReadonlySet<RuntimeKind> | undefined {
  const kinds = new Set<RuntimeKind>();
  const booleans = new Set<string>();
  for (const member of type.isUnion() ? type.types : [type]) {
    const kind = primitiveKind(member, allowLiterals);
    if (kind !== undefined) { kinds.add(kind); continue; }
    if ((member.flags & ts.TypeFlags.BooleanLiteral) === 0) return undefined;
    booleans.add(checker.typeToString(member));
  }
  if (booleans.size > 0) {
    if (!allowLiterals && booleans.size !== 2) return undefined;
    kinds.add("boolean");
  }
  return kinds.size === 0 ? undefined : kinds;
}

function primitiveKind(type: ts.Type, allowLiterals: boolean): RuntimeKind | undefined {
  for (const [flag, kind] of PRIMITIVE_KINDS) {
    if ((type.flags & flag) !== 0) return kind;
  }
  if (!allowLiterals) return undefined;
  if ((type.flags & ts.TypeFlags.StringLiteral) !== 0) return "string";
  if ((type.flags & ts.TypeFlags.NumberLiteral) !== 0) return "number";
  if ((type.flags & ts.TypeFlags.BigIntLiteral) !== 0) return "bigint";
  if ((type.flags & ts.TypeFlags.Null) !== 0) return "object";
  return undefined;
}
