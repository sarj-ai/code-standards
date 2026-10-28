/**
 * @fileoverview no-partial-type-predicate — an explicit primitive predicate must recognize every value it promises.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-partial-type-predicate.test.ts
 */
import { ASTUtils, AST_NODE_TYPES, ESLintUtils, type ParserServicesWithTypeInformation, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import { isNumberLiteralType } from "ts-api-utils";
import ts from "typescript";

import { privatePredicateBooleanFix } from "./_unused-private-binding.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { hasSeparatePredicateContract } from "./_has-separate-predicate-contract.js";
import { isGeneratedFile } from "./_paths.js";
import { staticString } from "./_static-string.js";
import { unwrapExpression } from "./_unwrap-expression.js";
import { uuidPredicateWitness } from "./_uuid-predicate-witness.js";

type Options = readonly [];
type MessageIds = "partialPredicate";
type FunctionNode = TSESTree.ArrowFunctionExpression | TSESTree.FunctionDeclaration | TSESTree.FunctionExpression;
type Primitive = string | number | bigint | boolean;
type PrimitiveKind = "string" | "number" | "bigint" | "boolean";

interface Predicate {
  readonly annotation: TSESTree.TSTypePredicate;
  readonly parameter: TSESTree.Identifier;
  readonly expression: TSESTree.Expression;
  readonly kind: PrimitiveKind;
  readonly input: ts.Type;
  readonly inputIsTarget: boolean;
}

const MAX_LENGTH_WITNESS = 256;

export const NO_PARTIAL_TYPE_PREDICATE_DOCUMENTATION = {
  summary: "Do not give a partial primitive filter an explicit type predicate that excludes valid values in the false branch.",
  rationale: "Type predicates narrow both branches, and TypeScript trusts their implementation. A positive-number or non-empty-string predicate can return false for a value belonging to its promised type, causing callers to treat that value as a different type.",
  remediation: "Use a boolean return for an intentional value filter, or recognize every member of the promised type. Preserve required callback and public contracts; a refined domain may need a distinct validated type. Recheck false-branch callers when changing a predicate.",
  category: "correctness",
  defaultLevel: "error",
  autofix: "safe",
  limitations: [
    "Automatic fixes replace the unsound predicate with boolean only for an unused private function declaration without overloads, exports, eval, comments in the predicate, or declaration-file ownership. Runtime checks are preserved; observed callable contracts remain manual.",
    "Requires type information and a non-generic, non-async function with one directly annotated parameter, an explicit broad string/number/bigint/boolean predicate and a single return. Literal, branded, structural, multi-primitive union, assertion, method and overloaded contracts are excluded; contextually typed callbacks are preserved.",
    "Recognizes double-negation truthiness, a boolean parameter return or one same-kind literal comparison, optionally after a matching typeof equality. Without a typeof check, the input must already belong to the target primitive, except for double negation. String length comparisons use only concrete witnesses up to 256 characters. Arithmetic, dynamic bounds and complex boolean conditions are not inferred.",
    "A broad string predicate returning local Schema.safeParse(parameter).success is also checked for a locally unchanged official z.uuid() or z.string().uuid() schema. The checker must resolve the namespace to installed node_modules/zod declaration files; local path aliases and opaque module resolution abstain. The const schema permits local parse/type/direct-export reads; every safeParse call must have exactly one direct argument, without options or spreads. Local aliases, method writes and opaque consumers abstain. Direct export alone is not mutation, but external consumer monkey-patching is not proved absent. Other value uses of its imported Zod namespace cause abstention. Transforms, brands, custom schemas, imported schemas and dynamic parse calls are excluded. Visible RegExp capabilities, regex literals or dynamic evaluation invalidate this initial native-pattern proof; external runtime monkeypatches are not inferred. This new schema profile has no automatic fix.",
    "A concrete member of the promised broad primitive must demonstrably return false. Numeric witnesses must also be assignable as literals to the declared input: broad number assignability alone does not prove membership in a numeric enum. Compiler-invalid target/input relations, any/never/generic inputs and opaque implementations abstain. This rule does not discourage total boundary guards or infer branded refinements. Generated files are excluded; tests remain checked.",
  ],
  references: ["https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-5.html#inferred-type-predicates"],
  examples: [
    { id: "boolean-value-filter", title: "Keep an intentional value filter boolean", outcome: "no-match", files: [{ path: "src/filter.ts", source: 'function isPositive(value: number): boolean { return value > 0; }' }], focusPath: "src/filter.ts", expectedCount: 0, public: true },
    { id: "partial-number-predicate", title: "Zero remains a number when the predicate returns false", outcome: "match", files: [{ path: "src/guard.ts", source: 'function isPositive(value: unknown): value is number { return typeof value === "number" && value > 0; }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "partial-uuid-predicate", scenarioId: "uuid", title: "A rejected UUID candidate can still be a string", outcome: "match", files: [{ path: "src/guard.ts", source: 'import { z } from "zod"; export const UuidSchema: z.ZodUUID = z.uuid(); export function isUuid(value: unknown): value is string { return UuidSchema.safeParse(value).success; }' }], installedDependencies: [{ module: "zod", version: "4.6.7" }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "boolean-uuid-filter", scenarioId: "uuid", title: "Keep a UUID value filter boolean", outcome: "no-match", files: [{ path: "src/filter.ts", source: 'import { z } from "zod"; export const UuidSchema: z.ZodUUID = z.uuid(); export function isUuid(value: unknown): boolean { return UuidSchema.safeParse(value).success; }' }], installedDependencies: [{ module: "zod", version: "4.6.7" }], focusPath: "src/filter.ts", expectedCount: 0, public: true },
    {
      id: "safe-autofix",
      title: "Retain an unused private filter without unsound narrowing",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; function isPositive(value: unknown): value is number { return typeof value === \"number\" && value > 0; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; function isPositive(value: unknown): boolean { return typeof value === \"number\" && value > 0; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "no-partial-type-predicate",
  documentation: NO_PARTIAL_TYPE_PREDICATE_DOCUMENTATION,
  meta: {
    type: "problem",
    fixable: "code",
    docs: { description: NO_PARTIAL_TYPE_PREDICATE_DOCUMENTATION.summary },
    schema: [],
    messages: { partialPredicate: "This predicate returns false for {{witness}}, which still belongs to `{{target}}`. Its false branch can therefore narrow unsafely. Use a boolean value filter or a predicate that recognizes every promised value." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text) || !context.sourceCode.parserServices?.program) return {};
    const services = ESLintUtils.getParserServices(context);
    function inspect(node: FunctionNode): void {
      const predicate = primitivePredicate(node, services);
      if (predicate === undefined) return;
      const uuidWitness = predicate.kind === "string" ? uuidPredicateWitness(predicate.expression, predicate.parameter, context.sourceCode, services) : undefined;
      if (uuidWitness !== undefined) {
        context.report({ node: predicate.annotation, messageId: "partialPredicate", data: { witness: showWitness(uuidWitness), target: "string" } });
        return;
      }
      const refinement = refinementExpression(predicate, context.sourceCode);
      if (refinement === undefined) return;
      const witness = rejectedWitness(refinement, predicate, context.sourceCode);
      if (witness === undefined) return;
      if (typeof witness === "number" && !numericWitnessInInput(witness, predicate.input)) return;
      context.report({ node: predicate.annotation, messageId: "partialPredicate", fix: privatePredicateBooleanFix(context.sourceCode, node, predicate.annotation, context.filename), data: {
        witness: showWitness(witness), target: predicate.kind,
      } });
    }
    return { FunctionDeclaration: inspect, FunctionExpression: inspect, ArrowFunctionExpression: inspect };
  },
});

function primitivePredicate(node: FunctionNode, services: ParserServicesWithTypeInformation): Predicate | undefined {
  const annotation = node.returnType?.typeAnnotation;
  const parameter = node.params[0];
  if (node.async || node.generator || node.typeParameters !== undefined || node.params.length !== 1 ||
    annotation?.type !== AST_NODE_TYPES.TSTypePredicate || annotation.asserts ||
    annotation.parameterName.type !== AST_NODE_TYPES.Identifier || annotation.typeAnnotation === undefined ||
    parameter?.type !== AST_NODE_TYPES.Identifier || parameter.name !== annotation.parameterName.name || parameter.typeAnnotation === undefined) return undefined;
  const checker = services.program.getTypeChecker();
  const tsFunction = services.esTreeNodeToTSNodeMap.get(node);
  if (ts.isMethodDeclaration(tsFunction)) return undefined;
  if (hasSeparatePredicateContract(tsFunction, checker)) return undefined;
  const target = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(annotation.typeAnnotation.typeAnnotation));
  const kind = primitiveKind(target);
  const input = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(parameter));
  const unsafe = ts.TypeFlags.Any | ts.TypeFlags.Never | ts.TypeFlags.TypeParameter | ts.TypeFlags.Conditional | ts.TypeFlags.IndexedAccess;
  if (kind === undefined || (input.flags & unsafe) !== 0 || !checker.isTypeAssignableTo(target, input)) return undefined;
  const expression = returnedExpression(node);
  return expression === undefined ? undefined : { annotation, parameter, expression, kind, input, inputIsTarget: checker.isTypeAssignableTo(input, target) };
}

function primitiveKind(type: ts.Type): PrimitiveKind | undefined {
  if ((type.flags & ts.TypeFlags.String) !== 0) return "string";
  if ((type.flags & ts.TypeFlags.Number) !== 0) return "number";
  if ((type.flags & ts.TypeFlags.BigInt) !== 0) return "bigint";
  if ((type.flags & ts.TypeFlags.Boolean) !== 0) return "boolean";
  return undefined;
}

/** Numeric enum assignability accepts broad number even when an individual literal is outside the enum. */
function numericWitnessInInput(value: number, input: ts.Type): boolean {
  return (input.isUnion() ? input.types : [input]).some((member) =>
    (member.flags & (ts.TypeFlags.Unknown | ts.TypeFlags.Number)) !== 0 ||
    (Number.isFinite(value) && isNumberLiteralType(member) && member.value === value));
}

function returnedExpression(node: FunctionNode): TSESTree.Expression | undefined {
  if (node.body === undefined) return undefined;
  if (node.body.type !== AST_NODE_TYPES.BlockStatement) return unwrapExpression(node.body);
  const statement = node.body.body[0];
  return node.body.body.length === 1 && statement?.type === AST_NODE_TYPES.ReturnStatement && statement.argument !== null ? unwrapExpression(statement.argument) : undefined;
}

function refinementExpression(predicate: Predicate, sourceCode: TSESLint.SourceCode): TSESTree.Expression | undefined {
  const expression = predicate.expression;
  if (expression.type !== AST_NODE_TYPES.LogicalExpression || expression.operator !== "&&") {
    return predicate.inputIsTarget || doubleNegation(expression, predicate.parameter, sourceCode) ? expression : undefined;
  }
  const check = unwrapExpression(expression.left);
  if (check.type !== AST_NODE_TYPES.BinaryExpression || (check.operator !== "===" && check.operator !== "==")) return undefined;
  for (const [left, right] of [[check.left, check.right], [check.right, check.left]] as const) {
    const value = unwrapExpression(left);
    if (value.type === AST_NODE_TYPES.UnaryExpression && value.operator === "typeof" &&
      sameParameter(value.argument, predicate.parameter, sourceCode) && staticString(right) === predicate.kind) return unwrapExpression(expression.right);
  }
  return undefined;
}

function doubleNegation(expression: TSESTree.Expression, parameter: TSESTree.Identifier, sourceCode: TSESLint.SourceCode): boolean {
  const outer = unwrapExpression(expression);
  if (outer.type !== AST_NODE_TYPES.UnaryExpression || outer.operator !== "!") return false;
  const inner = unwrapExpression(outer.argument);
  return inner.type === AST_NODE_TYPES.UnaryExpression && inner.operator === "!" && sameParameter(inner.argument, parameter, sourceCode);
}

function sameParameter(node: TSESTree.Node, parameter: TSESTree.Identifier, sourceCode: TSESLint.SourceCode): boolean {
  const value = unwrapExpression(node);
  if (value.type !== AST_NODE_TYPES.Identifier) return false;
  const binding = ASTUtils.findVariable(sourceCode.getScope(parameter), parameter.name);
  return binding !== null && binding === ASTUtils.findVariable(sourceCode.getScope(value), value.name);
}

function rejectedWitness(expression: TSESTree.Expression, predicate: Predicate, sourceCode: TSESLint.SourceCode): Primitive | undefined {
  if (doubleNegation(expression, predicate.parameter, sourceCode)) return falsyWitness(predicate.kind);
  if (predicate.kind === "boolean" && sameParameter(expression, predicate.parameter, sourceCode)) return false;
  if (expression.type !== AST_NODE_TYPES.BinaryExpression) return undefined;
  const bound = literal(expression.right);
  if (bound === undefined) return undefined;
  if (sameParameter(expression.left, predicate.parameter, sourceCode) && typeof bound === predicate.kind) {
    return witnesses(bound).find((value) => comparison(value, expression.operator, bound) === false);
  }
  const left = unwrapExpression(expression.left);
  if (predicate.kind !== "string" || typeof bound !== "number" || left.type !== AST_NODE_TYPES.MemberExpression || left.optional ||
    ASTUtils.getPropertyName(left) !== "length" || !sameParameter(left.object, predicate.parameter, sourceCode)) return undefined;
  return lengthWitnesses(bound).find((value) => comparison(value.length, expression.operator, bound) === false);
}

function falsyWitness(kind: PrimitiveKind): Primitive {
  switch (kind) {
    case "string": return "";
    case "number": return 0;
    case "bigint": return 0n;
    case "boolean": return false;
  }
}

function literal(node: TSESTree.Node): Primitive | undefined {
  const value = unwrapExpression(node);
  if (value.type === AST_NODE_TYPES.Literal && (typeof value.value === "string" || typeof value.value === "number" ||
    typeof value.value === "bigint" || typeof value.value === "boolean")) return value.value;
  if (value.type !== AST_NODE_TYPES.UnaryExpression || (value.operator !== "-" && value.operator !== "+")) return undefined;
  const operand = unwrapExpression(value.argument);
  if (operand.type === AST_NODE_TYPES.Literal && typeof operand.value === "bigint" && value.operator === "-") return -operand.value;
  if (operand.type !== AST_NODE_TYPES.Literal || typeof operand.value !== "number") return undefined;
  return value.operator === "-" ? -operand.value : operand.value;
}

function witnesses(bound: Primitive): readonly Primitive[] {
  switch (typeof bound) {
    case "string": return [bound, "", `${bound}x`];
    case "number": return [bound, 0, -1, 1, bound - 1, bound + 1, Number.NaN];
    case "bigint": return [bound, 0n, bound - 1n, bound + 1n];
    case "boolean": return [false, true];
  }
}

function lengthWitnesses(bound: number): readonly string[] {
  const values = ["", "x"];
  if (Number.isInteger(bound) && bound >= 0 && bound < MAX_LENGTH_WITNESS) values.push("x".repeat(bound), "x".repeat(bound + 1));
  return values;
}

function comparison(left: Primitive, operator: TSESTree.BinaryExpression["operator"], right: Primitive): boolean | undefined {
  if (operator === "==" || operator === "===") return left === right;
  if (operator === "!=" || operator === "!==") return left !== right;
  if (typeof left === "boolean" || typeof right === "boolean") return undefined;
  switch (operator) {
    case "<": return left < right;
    case "<=": return left <= right;
    case ">": return left > right;
    case ">=": return left >= right;
    default: return undefined;
  }
}

function showWitness(value: Primitive): string {
  if (typeof value === "bigint") return `\`${value}n\``;
  if (typeof value === "number" && Number.isNaN(value)) return "`NaN`";
  if (typeof value === "number" && !Number.isFinite(value)) return `\`${value}\``;
  return `\`${JSON.stringify(value)}\``;
}
