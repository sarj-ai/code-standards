/**
 * @fileoverview no-partial-type-predicate — an explicit primitive predicate must recognize every value it promises.
 *
 * Port of the 18.x `no-partial-type-predicate` rule. Typed: the
 * original returns no visitors without a program, so without tsrs (or when
 * tsrs cannot hold the file) this port reports nothing. The walk collects
 * functions whose syntax can carry a primitive predicate; `Program:exit` runs
 * the original's checks over tsrs's checker for each, then reports.
 */

import type { Type } from "tsrs/sync";

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { functionNode, nativeTypes, type NativeTypes } from "../utils/checked-native-source.js";
import { docsUrl } from "../utils/docs-url.js";
import { hasSeparatePredicateContract } from "../utils/has-separate-predicate-contract.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName, staticString } from "../utils/static-string.js";
import { type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";
import { privatePredicateBooleanFix } from "../utils/unused-private-binding.js";
import { uuidPredicateWitness } from "./_uuid-predicate-witness.js";

const NAME = "no-partial-type-predicate";

type FunctionNode = ESTree.ArrowFunctionExpression | ESTree.Function;
type Identifier = Node & { readonly type: "Identifier"; readonly name: string };
type Primitive = string | number | bigint | boolean;
type PrimitiveKind = "string" | "number" | "bigint" | "boolean";

interface Predicate {
  readonly annotation: ESTree.TSTypePredicate;
  readonly parameter: Identifier;
  readonly expression: Node;
  readonly kind: PrimitiveKind;
  readonly input: Type;
  readonly inputIsTarget: boolean;
}

/** The syntactic half of the original's `primitivePredicate`; tsrs answers the rest in `Program:exit`. */
interface Candidate {
  readonly node: FunctionNode;
  readonly annotation: ESTree.TSTypePredicate;
  readonly target: Node;
  readonly parameter: Identifier;
}

const MAX_LENGTH_WITNESS = 256;

function predicateCandidate(node: FunctionNode): Candidate | undefined {
  const annotation = node.returnType?.typeAnnotation;
  const parameter = node.params[0];
  if (node.async || node.generator || isPresent(node.typeParameters) || node.params.length !== 1 ||
    annotation?.type !== "TSTypePredicate" || annotation.asserts ||
    annotation.parameterName.type !== "Identifier" || !isPresent(annotation.typeAnnotation) ||
    parameter?.type !== "Identifier" || parameter.name !== annotation.parameterName.name || !isPresent(parameter.typeAnnotation)) return undefined;
  return { node, annotation, target: annotation.typeAnnotation.typeAnnotation, parameter };
}

function primitivePredicate(candidate: Candidate, native: NativeTypes): Predicate | undefined {
  const { node, annotation, parameter } = candidate;
  const { ast, checker, sync } = native;
  const tsFunction = functionNode(native, node);
  if (tsFunction === undefined || ast.isMethodDeclaration(tsFunction)) return undefined;
  if (hasSeparatePredicateContract(tsFunction, native)) return undefined;
  const targetNode = native.outerNode(candidate.target);
  const parameterNode = native.node(parameter);
  if (targetNode === undefined || parameterNode === undefined) return undefined;
  const target = checker.getTypeAtLocation(targetNode);
  const kind = primitiveKind(target, native);
  const input = checker.getTypeAtLocation(parameterNode);
  const flags = sync.TypeFlags;
  const unsafe = flags.Any | flags.Never | flags.TypeParameter | flags.Conditional | flags.IndexedAccess;
  if (kind === undefined || (input.flags & unsafe) !== 0 || !checker.isTypeAssignableTo(target, input)) return undefined;
  const expression = returnedExpression(node);
  return expression === undefined ? undefined : { annotation, parameter, expression, kind, input, inputIsTarget: checker.isTypeAssignableTo(input, target) };
}

function primitiveKind(type: Type, native: NativeTypes): PrimitiveKind | undefined {
  const flags = native.sync.TypeFlags;
  if ((type.flags & flags.String) !== 0) return "string";
  if ((type.flags & flags.Number) !== 0) return "number";
  if ((type.flags & flags.BigInt) !== 0) return "bigint";
  if ((type.flags & flags.Boolean) !== 0) return "boolean";
  return undefined;
}

/** Numeric enum assignability accepts broad number even when an individual literal is outside the enum. */
function numericWitnessInInput(value: number, input: Type, native: NativeTypes): boolean {
  const flags = native.sync.TypeFlags;
  return (input.isUnionType() ? input.getTypes() : [input]).some((member) =>
    (member.flags & (flags.Unknown | flags.Number)) !== 0 ||
    (Number.isFinite(value) && member.isNumberLiteralType() && member.value === value));
}

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description: "Do not give a partial primitive filter an explicit type predicate that excludes valid values in the false branch.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { partialPredicate: "This predicate returns false for {{witness}}, which still belongs to `{{target}}`. Its false branch can therefore narrow unsafely. Use a boolean value filter or a predicate that recognizes every promised value." },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let candidates: Candidate[] = [];

    function collect(node: FunctionNode): void {
      const candidate = predicateCandidate(node);
      if (candidate !== undefined) candidates.push(candidate);
    }

    function inspect(candidate: Candidate, native: NativeTypes): { readonly witness: Primitive; readonly target: string } | undefined {
      const sourceCode = context.sourceCode;
      const predicate = primitivePredicate(candidate, native);
      if (predicate === undefined) return undefined;
      const uuidWitness = predicate.kind === "string" ? uuidPredicateWitness(predicate.expression, predicate.parameter, sourceCode, native) : undefined;
      if (uuidWitness !== undefined) return { witness: uuidWitness, target: "string" };
      const refinement = refinementExpression(predicate, sourceCode);
      if (refinement === undefined) return undefined;
      const witness = rejectedWitness(refinement, predicate, sourceCode);
      if (witness === undefined) return undefined;
      if (typeof witness === "number" && !numericWitnessInInput(witness, predicate.input, native)) return undefined;
      return { witness, target: predicate.kind };
    }

    return {
      before() {
        tsrs = null;
        candidates = [];
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      FunctionDeclaration: collect,
      FunctionExpression: collect,
      ArrowFunctionExpression: collect,
      "Program:exit"() {
        if (candidates.length === 0 || tsrs === null) return;
        const found = tsrs.run((file) => {
          const native = nativeTypes(file);
          return candidates.map((candidate) => inspect(candidate, native));
        });
        if (found === null) return;
        candidates.forEach((candidate, i) => {
          const result = found[i];
          if (result === undefined) return;
          const fix = privatePredicateBooleanFix(context.sourceCode, candidate.node, candidate.annotation, context.filename);
          context.report({
            node: candidate.annotation, messageId: "partialPredicate",
            data: { witness: showWitness(result.witness), target: result.target },
            ...(fix !== null && { fix }),
          });
        });
      },
    };
  },
});

function returnedExpression(node: FunctionNode): Node | undefined {
  if (!isPresent(node.body)) return undefined;
  if (node.body.type !== "BlockStatement") return unwrapExpression(node.body);
  const statement = node.body.body[0];
  return node.body.body.length === 1 && statement?.type === "ReturnStatement" && statement.argument !== null ? unwrapExpression(statement.argument) : undefined;
}

function refinementExpression(predicate: Predicate, sourceCode: SourceCode): Node | undefined {
  const expression = predicate.expression;
  if (expression.type !== "LogicalExpression" || expression.operator !== "&&") {
    return predicate.inputIsTarget || doubleNegation(expression, predicate.parameter, sourceCode) ? expression : undefined;
  }
  const check = unwrapExpression(expression.left);
  if (check.type !== "BinaryExpression" || (check.operator !== "===" && check.operator !== "==")) return undefined;
  for (const [left, right] of [[check.left, check.right], [check.right, check.left]] as const) {
    const value = unwrapExpression(left);
    if (value.type === "UnaryExpression" && value.operator === "typeof" &&
      sameParameter(value.argument, predicate.parameter, sourceCode) && staticString(right) === predicate.kind) return unwrapExpression(expression.right);
  }
  return undefined;
}

function doubleNegation(expression: Node, parameter: Identifier, sourceCode: SourceCode): boolean {
  const outer = unwrapExpression(expression);
  if (outer.type !== "UnaryExpression" || outer.operator !== "!") return false;
  const inner = unwrapExpression(outer.argument);
  return inner.type === "UnaryExpression" && inner.operator === "!" && sameParameter(inner.argument, parameter, sourceCode);
}

function sameParameter(node: Node, parameter: Identifier, sourceCode: SourceCode): boolean {
  const value = unwrapExpression(node);
  if (value.type !== "Identifier") return false;
  const binding = findVariable(sourceCode.getScope(parameter), parameter.name);
  return binding !== null && binding === findVariable(sourceCode.getScope(value), value.name);
}

function rejectedWitness(expression: Node, predicate: Predicate, sourceCode: SourceCode): Primitive | undefined {
  if (doubleNegation(expression, predicate.parameter, sourceCode)) return falsyWitness(predicate.kind);
  if (predicate.kind === "boolean" && sameParameter(expression, predicate.parameter, sourceCode)) return false;
  if (expression.type !== "BinaryExpression") return undefined;
  const bound = literal(expression.right);
  if (bound === undefined) return undefined;
  if (sameParameter(expression.left, predicate.parameter, sourceCode) && typeof bound === predicate.kind) {
    return witnesses(bound).find((value) => comparison(value, expression.operator, bound) === false);
  }
  const left = unwrapExpression(expression.left);
  if (predicate.kind !== "string" || typeof bound !== "number" || left.type !== "MemberExpression" || left.optional ||
    getPropertyName(left) !== "length" || !sameParameter(left.object, predicate.parameter, sourceCode)) return undefined;
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

function literal(node: Node): Primitive | undefined {
  const value = unwrapExpression(node);
  if (value.type === "Literal" && (typeof value.value === "string" || typeof value.value === "number" ||
    typeof value.value === "bigint" || typeof value.value === "boolean")) return value.value;
  if (value.type !== "UnaryExpression" || (value.operator !== "-" && value.operator !== "+")) return undefined;
  const operand = unwrapExpression(value.argument);
  if (operand.type === "Literal" && typeof operand.value === "bigint" && value.operator === "-") return -operand.value;
  if (operand.type !== "Literal" || typeof operand.value !== "number") return undefined;
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

function comparison(left: Primitive, operator: ESTree.BinaryExpression["operator"], right: Primitive): boolean | undefined {
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
