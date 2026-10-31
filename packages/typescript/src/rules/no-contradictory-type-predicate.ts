/**
 * @fileoverview no-contradictory-type-predicate — primitive type guards must agree with both narrowing branches.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-contradictory-type-predicate.test.ts
 */
import { ASTUtils, AST_NODE_TYPES, ESLintUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import { privatePredicateBooleanFix } from "./_unused-private-binding.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { hasSeparatePredicateContract } from "./_has-separate-predicate-contract.js";
import { isGeneratedFile } from "./_paths.js";
import { staticString } from "./_static-string.js";
import { unwrapExpression } from "./_unwrap-expression.js";
import { contradictoryArrayPredicate } from "./_contradictory-array-predicate.js";

type Options = readonly [];
type MessageIds = "contradictoryPredicate" | "closedLiteralPredicate" | "nullAccepted" | "uncheckedArrayElements" | "uncheckedRecordFields";
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
  summary: "Keep explicit type predicates consistent with their primitive, array or record membership check.",
  rationale: "TypeScript trusts an explicit type predicate without verifying its implementation. A contradictory check can admit the wrong primitive, overclaim a closed literal or empty domain, accept null as a non-null object, or remove valid alternatives from the false branch.",
  remediation: "Match the predicate to every value the check accepts and rejects. Check literal membership for a closed domain and exclude null when promising a non-null object. Use a boolean return for an intentional value filter; preserve required public and callback contracts.",
  category: "correctness",
  defaultLevel: "error",
  autofix: "safe",
  limitations: [
    "Automatic fixes replace the unsound predicate with boolean only for an unused private function declaration without overloads, exports, eval, comments in the predicate, or declaration-file ownership. Runtime checks are preserved; observed callable contracts remain manual.",
    "Requires type information, an explicit predicate over a directly named parameter and a single returned positive typeof equality for the same scope-resolved parameter. Both strict and loose equality and reversed operands are supported.",
    "Recognizes broad primitive targets, finite primitive literal/nullish unions and never, with unknown or fully classified primitive/nullish inputs. Closed input domains are checked against the actual target, including finite numeric enum members. Mixed broad-and-literal, branded, unique-symbol, structural, generic, asserted, declaration-only and multi-statement validators are excluded rather than guessed.",
    "For the intrinsic object target, typeof-object also admits null only when the declared input admits null and strictNullChecks is enabled. This narrow check does not infer structural property validation or classify other object/function relationships. Overloaded implementations, contextually typed callbacks and methods with class heritage or contextual object contracts retain their separate callable domain.",
    "Compiler-invalid predicate target/input relations and typeof comparisons impossible for the input remain with existing compiler and unnecessary-condition controls. This rule does not validate arbitrary predicates or runtime refinements. Generated files are excluded; tests remain checked.",
    "A sole native Array.isArray call on unknown cannot establish a plain primitive-element array target. Standard-library call signatures and an unshadowed Array binding are required. Element validators, any/unknown elements, tuples, enums, branded or opaque elements and independent callable contracts abstain. Visible Array or host-global aliases, mutation, escapes, extracted methods, any value constructor or unresolved computed-property access and unrelated Array namespace uses disable this proof: structural receiver types cannot establish runtime constructor identity. Native Reflect value uses and Object prototype/descriptor reflection or namespace aliases also withdraw authority. Indirect opaque runtime replacements are not inferred.",
    "For a same-file nongeneric named record with a required data property, a sole typeof-object check, optionally conjoined with a null exclusion, cannot establish that property from unknown or object input. Optional-only records, dictionaries, classes, imported/generic contracts and implementations with field checks are excluded. A non-null object without the required own property supplies the contradiction. The same unused-private predicate proof may remove its unobserved narrowing contract; observed callable contracts and sole named-type uses remain manual.",
  ],
  references: ["https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-5.html#inferred-type-predicates"],
  examples: [
    { id: "consistent-primitive-predicate", title: "Agree with the checked primitive", outcome: "no-match", files: [{ path: "src/guard.ts", source: 'function isText(value: unknown): value is string { return typeof value === "string"; }' }], focusPath: "src/guard.ts", expectedCount: 0, public: true },
    { id: "contradictory-primitive-predicate", title: "Do not promise a different primitive", outcome: "match", files: [{ path: "src/guard.ts", source: 'function isText(value: unknown): value is string { return typeof value === "number"; }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "closed-literal-check", scenarioId: "closed-literal-domain", title: "A closed input supplies the literal evidence", outcome: "no-match", files: [{ path: "src/guard.ts", source: 'function ready(value: "ready" | null): value is "ready" { return typeof value === "string"; }' }], focusPath: "src/guard.ts", expectedCount: 0, public: true },
    { id: "overclaimed-literal", scenarioId: "closed-literal-domain", title: "A string check admits other strings", outcome: "match", files: [{ path: "src/guard.ts", source: 'function ready(value: unknown): value is "ready" { return typeof value === "string"; }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "complete-object-check", scenarioId: "intrinsic-null", title: "Exclude null and recognize non-primitive functions", outcome: "no-match", files: [{ path: "src/guard.ts", source: 'function nonPrimitive(value: unknown): value is object { return (typeof value === "object" && value !== null) || typeof value === "function"; }' }], focusPath: "src/guard.ts", expectedCount: 0, public: true },
    { id: "object-check-admits-null", scenarioId: "intrinsic-null", title: "A typeof-object check also accepts null", outcome: "match", files: [{ path: "src/guard.ts", source: 'function nonPrimitive(value: unknown): value is object { return typeof value === "object"; }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "empty-domain-never-succeeds", scenarioId: "empty-domain", title: "An empty target has no successful member", outcome: "no-match", files: [{ path: "src/guard.ts", source: 'function impossible(value: unknown): value is never { return false; }' }], focusPath: "src/guard.ts", expectedCount: 0, public: true },
    { id: "empty-domain-check-succeeds", scenarioId: "empty-domain", title: "Numbers cannot belong to an empty target", outcome: "match", files: [{ path: "src/guard.ts", source: 'function impossible(value: unknown): value is never { return typeof value === "number"; }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "array-elements-unchecked", scenarioId: "array-elements", title: "Array membership alone does not prove text elements", outcome: "match", files: [{ path: "src/guard.ts", source: 'function texts(value: unknown): value is string[] { return Array.isArray(value); }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "array-elements-validated", scenarioId: "array-elements", title: "Establish the element domain at the boundary", outcome: "no-match", files: [{ path: "src/guard.ts", source: 'function texts(value: unknown): value is string[] { return Array.isArray(value) && value.every((item: unknown) => typeof item === "string"); }' }], focusPath: "src/guard.ts", expectedCount: 0, public: true },
    { id: "record-fields-unchecked", scenarioId: "record-fields", title: "Object membership does not establish required fields", outcome: "match", files: [{ path: "src/guard.ts", source: 'type Account = { id: string }; function account(value: unknown): value is Account { return typeof value === "object" && value !== null; }' }], focusPath: "src/guard.ts", expectedCount: 1, public: true },
    { id: "record-fields-validated", scenarioId: "record-fields", title: "Establish fields before promising the record", outcome: "no-match", files: [{ path: "src/guard.ts", source: 'type Account = { id: string }; function account(value: unknown): value is Account { return typeof value === "object" && value !== null && "id" in value && typeof value.id === "string"; }' }], focusPath: "src/guard.ts", expectedCount: 0, public: true },
    {
      id: "safe-autofix",
      title: "Retain an unused private filter without unsound narrowing",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; function isText(value: unknown): value is string { return typeof value === \"number\"; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; function isText(value: unknown): boolean { return typeof value === \"number\"; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "no-contradictory-type-predicate",
  documentation: NO_CONTRADICTORY_TYPE_PREDICATE_DOCUMENTATION,
  meta: {
    type: "problem",
    fixable: "code",
    docs: { description: NO_CONTRADICTORY_TYPE_PREDICATE_DOCUMENTATION.summary },
    schema: [],
    messages: {
      contradictoryPredicate: "This predicate promises `{{promised}}`, but its typeof check recognizes only `{{checked}}`. Align both true and false branch narrowing with the check, or return boolean for a partial check.",
      closedLiteralPredicate: "This typeof check does not match the closed literal contract `{{promised}}` for its declared input. Check literal membership or return boolean for a value filter.",
      nullAccepted: "This typeof-object check accepts null, but the predicate promises non-null object. Exclude null or declare the actual nullable domain; preserve required callable contracts.",
      uncheckedArrayElements: "Array.isArray accepts arrays with elements outside `{{promised}}`. Validate each element or retain an honest unknown-element array contract; preserve required callable contracts.",
      uncheckedRecordFields: "This object check does not establish the required fields of `{{promised}}`. Parse a focused object schema or validate its required fields before promising the record.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text) || !context.sourceCode.parserServices?.program) return {};
    const services = ESLintUtils.getParserServices(context);
    const checker = services.program.getTypeChecker();
    const uncheckedArray = contradictoryArrayPredicate(context.sourceCode, services);
    const pendingArrays: { readonly node: FunctionNode; readonly annotation: TSESTree.TSTypePredicate; readonly promised: string }[] = [];

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
      if (check !== undefined && !sameParameter(parameter, check.parameter, context.sourceCode)) return;
      const input = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(check?.parameter ?? parameter));
      const target = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(annotation.typeAnnotation.typeAnnotation));
      if (!checker.isTypeAssignableTo(target, input)) return;
      if (shallowRecordCheck(expression, parameter, input, target, context.sourceCode, checker, services.esTreeNodeToTSNodeMap.get(node).getSourceFile())) {
        context.report({ node: annotation, messageId: "uncheckedRecordFields", fix: privatePredicateBooleanFix(context.sourceCode, node, annotation, context.filename), data: { promised: checker.typeToString(target) } });
        return;
      }
      if (check === undefined) {
        if (uncheckedArray.matches(expression, parameter, input, target)) pendingArrays.push({ node, annotation, promised: checker.typeToString(target) });
        return;
      }
      const options = services.program.getCompilerOptions();
      const messageId = contradiction(input, target, check.kind, checker, options.strictNullChecks ?? options.strict ?? false);
      if (messageId === undefined) return;
      context.report({ node: annotation, messageId, fix: privatePredicateBooleanFix(context.sourceCode, node, annotation, context.filename), data: {
        promised: checker.typeToString(target), checked: check.kind,
      } });
    }

    return {
      FunctionDeclaration: inspect, FunctionExpression: inspect, ArrowFunctionExpression: inspect,
      MemberExpression: uncheckedArray.observeConstructor,
      "ObjectPattern > Property": uncheckedArray.observeConstructor,
      "Program:exit"(): void {
        if (pendingArrays.length === 0 || !uncheckedArray.stable()) return;
        for (const { node, annotation, promised } of pendingArrays) context.report({ node: annotation, messageId: "uncheckedArrayElements", fix: privatePredicateBooleanFix(context.sourceCode, node, annotation, context.filename), data: { promised } });
      },
    };
  },
});

function shallowRecordCheck(expression: TSESTree.Expression, parameter: TSESTree.Identifier, input: ts.Type, target: ts.Type,
  sourceCode: TSESLint.SourceCode, checker: ts.TypeChecker, source: ts.SourceFile): boolean {
  if ((input.flags & (ts.TypeFlags.Unknown | ts.TypeFlags.NonPrimitive)) === 0 || (target.flags & ts.TypeFlags.Object) === 0 ||
    target.isUnionOrIntersection() || checker.isArrayType(target) || checker.isTupleType(target) || checker.getIndexInfosOfType(target).length !== 0) return false;
  const declarations = (target.aliasSymbol ?? target.getSymbol())?.getDeclarations();
  if (declarations === undefined || declarations.length !== 1 || !declarations.every(declaration => declaration.getSourceFile() === source &&
    (ts.isInterfaceDeclaration(declaration) || ts.isTypeAliasDeclaration(declaration)) && !declaration.typeParameters?.length)) return false;
  if (!checker.getPropertiesOfType(target).some(property => (property.flags & ts.SymbolFlags.Optional) === 0 &&
    property.getDeclarations()?.some(declaration => ts.isPropertySignature(declaration) && declaration.type !== undefined))) return false;
  const value = unwrapExpression(expression);
  const direct = typeofCheck(value);
  if (direct !== undefined) return direct.kind === "object" && sameParameter(parameter, direct.parameter, sourceCode);
  if (value.type !== AST_NODE_TYPES.LogicalExpression || value.operator !== "&&") return false;
  for (const [left, right] of [[value.left, value.right], [value.right, value.left]] as const) {
    const check = typeofCheck(left);
    const excluded = unwrapExpression(right);
    if (check?.kind !== "object" || !sameParameter(parameter, check.parameter, sourceCode) ||
      excluded.type !== AST_NODE_TYPES.BinaryExpression || (excluded.operator !== "!==" && excluded.operator !== "!=")) continue;
    for (const [tested, sentinel] of [[excluded.left, excluded.right], [excluded.right, excluded.left]] as const) {
      if (tested.type === AST_NODE_TYPES.Identifier && sentinel.type === AST_NODE_TYPES.Literal && sentinel.value === null &&
        sameParameter(parameter, tested, sourceCode)) return true;
    }
  }
  return false;
}

function contradiction(input: ts.Type, target: ts.Type, checked: RuntimeKind, checker: ts.TypeChecker, strictNulls: boolean): MessageIds | undefined {
  if (strictNulls && checked === "object" && (target.flags & ts.TypeFlags.NonPrimitive) !== 0 && admitsNull(input)) return "nullAccepted";
  const possible = inputKinds(input, checker);
  if (possible === undefined || !possible.has(checked)) return undefined;
  if ((target.flags & ts.TypeFlags.Never) !== 0) return "contradictoryPredicate";
  const promised = primitiveKinds(target, checker, false);
  if (promised !== undefined) {
    return !promised.has(checked) || [...promised].some((kind) => kind !== checked && possible.has(kind)) ? "contradictoryPredicate" : undefined;
  }
  return closedLiteralContradiction(input, target, checked, checker) ? "closedLiteralPredicate" : undefined;
}

function admitsNull(input: ts.Type): boolean {
  return (input.flags & ts.TypeFlags.Unknown) !== 0 || (input.isUnion() ? input.types : [input]).some((member) => (member.flags & ts.TypeFlags.Null) !== 0);
}

function closedLiteralContradiction(input: ts.Type, target: ts.Type, checked: RuntimeKind, checker: ts.TypeChecker): boolean {
  const members = target.isUnion() ? target.types : [target];
  const literalFlags = ts.TypeFlags.StringLiteral | ts.TypeFlags.NumberLiteral | ts.TypeFlags.BigIntLiteral | ts.TypeFlags.BooleanLiteral | ts.TypeFlags.Null | ts.TypeFlags.Undefined;
  if (!members.every((member) => (member.flags & literalFlags) !== 0)) return false;
  if (members.some((member) => literalKind(member, checker) !== checked)) return true;
  if ((input.flags & ts.TypeFlags.Unknown) !== 0) return checked !== "undefined";
  return (input.isUnion() ? input.types : [input]).some((member) => literalKind(member, checker) === checked && !checker.isTypeAssignableTo(member, target));
}

function literalKind(type: ts.Type, checker: ts.TypeChecker): RuntimeKind | undefined {
  if ((type.flags & ts.TypeFlags.BooleanLiteral) !== 0) return "boolean";
  return primitiveKinds(type, checker, true)?.values().next().value;
}

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
