/**
 * @fileoverview no-contradictory-type-predicate — primitive type guards must agree with both narrowing branches.
 *
 * Port of the 18.x `no-contradictory-type-predicate` rule. Typed: the
 * original returns no visitors without a program, so without tsrs (or when
 * tsrs cannot hold the file) this port reports nothing. The walk collects
 * predicate functions and constructor reads; `Program:exit` runs the
 * original's checks over tsrs's checker for each function, then reports.
 *
 * Under Oxlint the original never reports: it requires
 * `node.typeParameters === undefined`, and Oxlint gives `null`. This port
 * treats both as absent, so it reports as the original does under ESLint.
 */

import type { Node as TsNode } from "tsrs/ast";
import type { Type } from "tsrs/sync";

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { functionNode, type NativeTypes, nativeTypes, unionMembers } from "../utils/checked-native-source.js";
import { docsUrl } from "../utils/docs-url.js";
import { hasSeparatePredicateContract } from "../utils/has-separate-predicate-contract.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, staticString } from "../utils/static-string.js";
import { type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";
import { privatePredicateBooleanFix } from "../utils/unused-private-binding.js";
import { type ArrayPredicateProof, contradictoryArrayPredicate } from "./_contradictory-array-predicate.js";

const NAME = "no-contradictory-type-predicate";

type MessageIds = "contradictoryPredicate" | "closedLiteralPredicate" | "nullAccepted" | "uncheckedArrayElements" | "uncheckedRecordFields";
type FunctionNode = ESTree.ArrowFunctionExpression | ESTree.Function;
type Identifier = Node & { readonly type: "Identifier"; readonly name: string };
const RUNTIME_KINDS = ["string", "number", "bigint", "boolean", "symbol", "undefined", "object", "function"] as const;
type RuntimeKind = (typeof RUNTIME_KINDS)[number];
const ANY_RUNTIME_KIND: ReadonlySet<RuntimeKind> = new Set(RUNTIME_KINDS);

interface TypeofCheck {
  readonly parameter: Identifier;
  readonly kind: RuntimeKind;
}

interface Candidate {
  readonly node: FunctionNode;
  readonly annotation: ESTree.TSTypePredicate;
  readonly target: Node;
  readonly parameter: Identifier;
  readonly expression: Node;
  readonly check: TypeofCheck | undefined;
}

interface Finding {
  readonly candidate: Candidate;
  readonly messageId: MessageIds;
  readonly data: Readonly<Record<string, string>>;
}

interface ParameterPredicate {
  readonly annotation: ESTree.TSTypePredicate;
  readonly name: string;
  readonly target: Node;
}

/** The `parameter is Type` return annotation of a plain (not async, generator or generic) function. */
function parameterPredicate(node: FunctionNode): ParameterPredicate | undefined {
  const annotation = node.returnType?.typeAnnotation;
  if (node.async || node.generator || isPresent(node.typeParameters) || annotation?.type !== "TSTypePredicate" ||
    annotation.asserts || annotation.parameterName.type !== "Identifier" || !isPresent(annotation.typeAnnotation)) return undefined;
  return { annotation, name: annotation.parameterName.name, target: annotation.typeAnnotation.typeAnnotation };
}

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description: "Keep explicit type predicates consistent with their primitive, array or record membership check.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      contradictoryPredicate: "This predicate promises `{{promised}}`, but its typeof check recognizes only `{{checked}}`. Align both true and false branch narrowing with the check, or return boolean for a partial check.",
      closedLiteralPredicate: "This typeof check does not match the closed literal contract `{{promised}}` for its declared input. Check literal membership or return boolean for a value filter.",
      nullAccepted: "This typeof-object check accepts null, but the predicate promises non-null object. Exclude null or declare the actual nullable domain; preserve required callable contracts.",
      uncheckedArrayElements: "Array.isArray accepts arrays with elements outside `{{promised}}`. Validate each element or retain an honest unknown-element array contract; preserve required callable contracts.",
      uncheckedRecordFields: "This object check does not establish the required fields of `{{promised}}`. Parse a focused object schema or validate its required fields before promising the record.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let candidates: Candidate[] = [];
    let uncheckedArray: ArrayPredicateProof | null = null;

    /** The original's syntactic checks, before its first type query. */
    function collect(node: FunctionNode): void {
      const predicate = parameterPredicate(node);
      if (predicate === undefined) return;
      const parameter = node.params.find((candidate) => candidate.type === "Identifier" && candidate.name === predicate.name);
      const expression = singleReturn(node);
      if (parameter?.type !== "Identifier" || !isPresent(parameter.typeAnnotation) || expression === undefined) return;
      const check = typeofCheck(expression);
      if (check !== undefined && !sameParameter(parameter, check.parameter, context.sourceCode)) return;
      candidates.push({ node, annotation: predicate.annotation, target: predicate.target, parameter, expression, check });
    }

    /** The original's typed checks for one function, in its order. */
    function inspect(candidate: Candidate, native: NativeTypes, strictNulls: boolean): Finding | undefined {
      const { checker } = native;
      const tsFunction = functionNode(native, candidate.node);
      if (tsFunction === undefined || hasSeparatePredicateContract(tsFunction, native)) return undefined;
      const inputNode = native.node(candidate.check?.parameter ?? candidate.parameter);
      const targetNode = native.outerNode(candidate.target);
      if (inputNode === undefined || targetNode === undefined) return undefined;
      const input = checker.getTypeAtLocation(inputNode);
      const target = checker.getTypeAtLocation(targetNode);
      if (!checker.isTypeAssignableTo(target, input)) return undefined;
      if (shallowRecordCheck(candidate.expression, candidate.parameter, input, target, context.sourceCode, native)) {
        return { candidate, messageId: "uncheckedRecordFields", data: { promised: checker.typeToString(target) } };
      }
      if (candidate.check === undefined) {
        // The original defers these to `Program:exit`, where `stable()` has seen every constructor read.
        return uncheckedArray?.matches(native, candidate.expression, candidate.parameter, input, target) === true
          ? { candidate, messageId: "uncheckedArrayElements", data: { promised: checker.typeToString(target) } } : undefined;
      }
      const messageId = contradiction(input, target, candidate.check.kind, native, strictNulls);
      if (messageId === undefined) return undefined;
      return { candidate, messageId, data: { promised: checker.typeToString(target), checked: candidate.check.kind } };
    }

    function report({ candidate, messageId, data }: Finding): void {
      const fix = privatePredicateBooleanFix(context.sourceCode, candidate.node, candidate.annotation, context.filename);
      context.report({ node: candidate.annotation, messageId, data, ...(fix !== null && { fix }) });
    }

    function observeConstructor(member: ESTree.MemberExpression | ESTree.ObjectProperty): void {
      uncheckedArray?.observeConstructor(member);
    }

    return {
      before(): boolean | void {
        tsrs = null;
        candidates = [];
        uncheckedArray = null;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        if (tsrs === null) return false;
        uncheckedArray = contradictoryArrayPredicate(context.sourceCode);
      },
      FunctionDeclaration: collect,
      FunctionExpression: collect,
      ArrowFunctionExpression: collect,
      MemberExpression: observeConstructor,
      "ObjectPattern > Property": observeConstructor,
      "Program:exit"() {
        if (candidates.length === 0 || tsrs === null) return;
        const options = tsrs.compilerOptions;
        const strictNulls = Boolean(options.strictNullChecks ?? options.strict ?? false);
        const found = tsrs.run((file) => {
          const native = nativeTypes(file);
          return candidates.map((candidate) => inspect(candidate, native, strictNulls));
        });
        if (found === null) return;
        const arraysStable = uncheckedArray?.stable() === true;
        for (const finding of found) {
          if (finding === undefined) continue;
          if (finding.messageId === "uncheckedArrayElements" && !arraysStable) continue;
          report(finding);
        }
      },
    };
  },
});

/** An `object` typeof check promising a closed local record whose required fields it never validates. */
function shallowRecordCheck(expression: Node, parameter: Identifier, input: Type, target: Type, sourceCode: SourceCode, native: NativeTypes): boolean {
  return isOpenInputToPlainObject(input, target, native) && hasOneLocalNonGenericDeclaration(target, native) &&
    hasRequiredTypedProperty(target, native) && isNonNullObjectCheck(unwrapExpression(expression), parameter, sourceCode);
}

/** An unknown or `object` input narrowed to one object type that is no union, intersection, array, tuple or index signature. */
function isOpenInputToPlainObject(input: Type, target: Type, native: NativeTypes): boolean {
  const { checker } = native;
  const flags = native.sync.TypeFlags;
  return (input.flags & (flags.Unknown | flags.NonPrimitive)) !== 0 && (target.flags & flags.Object) !== 0 &&
    !target.isUnionType() && !target.isIntersectionType() && !checker.isArrayType(target) && !checker.isTupleType(target) &&
    checker.getIndexInfosOfType(target).length === 0;
}

/** Declared once, in this file, by a non-generic interface or type alias. */
function hasOneLocalNonGenericDeclaration(target: Type, native: NativeTypes): boolean {
  const declarations = (target.getAliasSymbol() ?? target.getSymbol())?.declarations;
  const kinds = native.ast.SyntaxKind;
  return declarations !== undefined && declarations.length === 1 && declarations.every((handle) => {
    if (handle.path !== native.source.path || (handle.kind !== kinds.InterfaceDeclaration && handle.kind !== kinds.TypeAliasDeclaration)) return false;
    const declaration = handle.resolve() as (TsNode & { readonly typeParameters?: readonly unknown[] | undefined }) | undefined;
    return declaration !== undefined && !declaration.typeParameters?.length;
  });
}

/** Has a required property declared by a property signature with a type annotation. */
function hasRequiredTypedProperty(target: Type, native: NativeTypes): boolean {
  const kinds = native.ast.SyntaxKind;
  return native.checker.getPropertiesOfType(target).some((property) => (property.flags & native.sync.SymbolFlags.Optional) === 0 &&
    property.declarations.some((handle) => {
      if (handle.kind !== kinds.PropertySignature) return false;
      const declaration = handle.resolve() as (TsNode & { readonly type?: unknown }) | undefined;
      return declaration !== undefined && declaration.type !== undefined;
    }));
}

/** `typeof parameter === "object"`, alone or joined by `&&` with `parameter !== null`, in either order. */
function isNonNullObjectCheck(value: Node, parameter: Identifier, sourceCode: SourceCode): boolean {
  const direct = typeofCheck(value);
  if (direct !== undefined) return direct.kind === "object" && sameParameter(parameter, direct.parameter, sourceCode);
  if (value.type !== "LogicalExpression" || value.operator !== "&&") return false;
  return ([[value.left, value.right], [value.right, value.left]] as const).some(([left, right]) => {
    const check = typeofCheck(left);
    return check?.kind === "object" && sameParameter(parameter, check.parameter, sourceCode) &&
      excludesNull(unwrapExpression(right), parameter, sourceCode);
  });
}

/** `parameter !== null` or `parameter != null`, in either order. */
function excludesNull(excluded: Node, parameter: Identifier, sourceCode: SourceCode): boolean {
  if (excluded.type !== "BinaryExpression" || (excluded.operator !== "!==" && excluded.operator !== "!=")) return false;
  return ([[excluded.left, excluded.right], [excluded.right, excluded.left]] as const).some(([tested, sentinel]) =>
    tested.type === "Identifier" && sentinel.type === "Literal" && sentinel.value === null && sameParameter(parameter, tested, sourceCode));
}

function contradiction(input: Type, target: Type, checked: RuntimeKind, native: NativeTypes, strictNulls: boolean): MessageIds | undefined {
  const flags = native.sync.TypeFlags;
  if (strictNulls && checked === "object" && (target.flags & flags.NonPrimitive) !== 0 && admitsNull(input, native)) return "nullAccepted";
  const possible = inputKinds(input, native);
  if (possible === undefined || !possible.has(checked)) return undefined;
  if ((target.flags & flags.Never) !== 0) return "contradictoryPredicate";
  const promised = primitiveKinds(target, native, false);
  if (promised !== undefined) {
    return !promised.has(checked) || [...promised].some((kind) => kind !== checked && possible.has(kind)) ? "contradictoryPredicate" : undefined;
  }
  return closedLiteralContradiction(input, target, checked, native) ? "closedLiteralPredicate" : undefined;
}

function admitsNull(input: Type, native: NativeTypes): boolean {
  const flags = native.sync.TypeFlags;
  return (input.flags & flags.Unknown) !== 0 || unionMembers(input).some((member) => (member.flags & flags.Null) !== 0);
}

function closedLiteralContradiction(input: Type, target: Type, checked: RuntimeKind, native: NativeTypes): boolean {
  const flags = native.sync.TypeFlags;
  const targetMembers = unionMembers(target);
  const literalFlags = flags.StringLiteral | flags.NumberLiteral | flags.BigIntLiteral | flags.BooleanLiteral | flags.Null | flags.Undefined;
  if (!targetMembers.every((member) => (member.flags & literalFlags) !== 0)) return false;
  if (targetMembers.some((member) => literalKind(member, native) !== checked)) return true;
  if ((input.flags & flags.Unknown) !== 0) return checked !== "undefined";
  return unionMembers(input).some((member) => literalKind(member, native) === checked && !native.checker.isTypeAssignableTo(member, target));
}

function literalKind(type: Type, native: NativeTypes): RuntimeKind | undefined {
  if ((type.flags & native.sync.TypeFlags.BooleanLiteral) !== 0) return "boolean";
  return primitiveKinds(type, native, true)?.values().next().value;
}

function singleReturn(node: FunctionNode): Node | undefined {
  if (node.body === undefined || node.body === null) return undefined;
  if (node.body.type !== "BlockStatement") return node.body;
  const statement = node.body.body[0];
  return node.body.body.length === 1 && statement?.type === "ReturnStatement" && statement.argument !== null ? statement.argument : undefined;
}

function typeofCheck(expression: Node): TypeofCheck | undefined {
  const value = unwrapExpression(expression);
  if (value.type !== "BinaryExpression" || (value.operator !== "===" && value.operator !== "==")) return undefined;
  for (const [tested, expected] of [[value.left, value.right], [value.right, value.left]] as const) {
    const operand = unwrapExpression(tested);
    const expectedKind = staticString(expected);
    const kind = RUNTIME_KINDS.find((candidate) => candidate === expectedKind);
    if (operand.type !== "UnaryExpression" || operand.operator !== "typeof" ||
      operand.argument.type !== "Identifier" || kind === undefined) continue;
    return { parameter: operand.argument as Identifier, kind };
  }
  return undefined;
}

function sameParameter(declared: Identifier, tested: Identifier, sourceCode: SourceCode): boolean {
  const parameter = findVariable(sourceCode.getScope(declared), declared.name);
  return parameter !== null && parameter === findVariable(sourceCode.getScope(tested), tested.name);
}

function inputKinds(type: Type, native: NativeTypes): ReadonlySet<RuntimeKind> | undefined {
  if ((type.flags & native.sync.TypeFlags.Unknown) !== 0) return ANY_RUNTIME_KIND;
  return primitiveKinds(type, native, true);
}

function primitiveKinds(type: Type, native: NativeTypes, allowLiterals: boolean): ReadonlySet<RuntimeKind> | undefined {
  const kinds = new Set<RuntimeKind>();
  const booleans = new Set<string>();
  for (const member of unionMembers(type)) {
    const kind = primitiveKind(member, native, allowLiterals);
    if (kind !== undefined) { kinds.add(kind); continue; }
    if ((member.flags & native.sync.TypeFlags.BooleanLiteral) === 0) return undefined;
    // TypeScript names boolean literals "true"/"false"; tsrs gives the value.
    booleans.add(String((member as Type & { readonly value: unknown }).value));
  }
  if (booleans.size > 0) {
    if (!allowLiterals && booleans.size !== 2) return undefined;
    kinds.add("boolean");
  }
  return kinds.size === 0 ? undefined : kinds;
}

function primitiveKind(type: Type, native: NativeTypes, allowLiterals: boolean): RuntimeKind | undefined {
  const flags = native.sync.TypeFlags;
  const primitives: readonly (readonly [number, RuntimeKind])[] = [
    [flags.String, "string"], [flags.Number, "number"], [flags.BigInt, "bigint"],
    [flags.ESSymbol, "symbol"], [flags.Undefined, "undefined"],
  ];
  for (const [flag, kind] of primitives) {
    if ((type.flags & flag) !== 0) return kind;
  }
  if (!allowLiterals) return undefined;
  if ((type.flags & flags.StringLiteral) !== 0) return "string";
  if ((type.flags & flags.NumberLiteral) !== 0) return "number";
  if ((type.flags & flags.BigIntLiteral) !== 0) return "bigint";
  if ((type.flags & flags.Null) !== 0) return "object";
  return undefined;
}
