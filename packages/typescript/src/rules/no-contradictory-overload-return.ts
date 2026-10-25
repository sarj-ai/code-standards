/**
 * @fileoverview no-contradictory-overload-return — preserve literal overload input/result relationships.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-contradictory-overload-return.test.ts
 */
import { AST_NODE_TYPES, ESLintUtils, type ParserServicesWithTypeInformation, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isUnusedPrivateBinding } from "./_unused-private-binding.js";
import { isGeneratedFile } from "./_paths.js";

type Options = readonly [];
type MessageIds = "contradictoryReturn";
type Primitive = string | number | boolean | null;
interface LiteralValue { readonly node: ts.Expression; readonly value: Primitive; }
interface LiteralCase { readonly input: LiteralValue; readonly output: ts.Type; readonly declaration: ts.FunctionDeclaration; }
type Branch =
  | { readonly kind: "literal"; readonly node: ts.Expression; readonly value: LiteralValue }
  | { readonly kind: "record"; readonly node: ts.Expression; readonly values: ReadonlyMap<string, LiteralValue> };
const LIMIT = 32;

export const NO_CONTRADICTORY_OVERLOAD_RETURN_DOCUMENTATION = {
  summary: "Preserve the input/result relationship promised by literal overloads.",
  rationale: "TypeScript checks an overload implementation against an overall envelope, without proving each input/result relationship. A function can compile while returning the opposite domain variant for every advertised literal input.",
  remediation: "Return the variant promised for each input. Prefer a checked case map or separate variant-specific operations when that makes the relationship explicit; retain overloads required by public APIs.",
  category: "correctness", defaultLevel: "warning", autofix: "safe",
  limitations: [
    "Automatic fixes align only an unused private complete same-file overload group with its existing literal implementation results. Binding aliases, exports, merges, eval, declaration files, comments, nonliteral result syntax and observed callers preserve manual ownership; runtime checks and returned values never change.",
    "Requires type information and a top-level non-generic, synchronous function with two to 32 unique, single-required-parameter overloads. Each public input must be a directly authored string, finite number, boolean or null literal. Broad, duplicate, aliased, optional, rest and multi-parameter inputs are excluded.",
    "The implementation must have one required identifier parameter and only return a strict literal equality/inequality conditional. Both branches must be primitive literals or flat objects containing only primitive literal property assignments. Calls, computed keys, getters, spreads, duplicate keys and __proto__ are excluded.",
    "Reports only a concrete returned literal incompatible with its primitive contract or an explicit returned property incompatible with the corresponding primitive property contract. Missing properties, arbitrary structural incompatibility, brands, enums, opaque types, effects and general control flow are outside this proof.",
    "Compiler-invalid implementation input/output envelopes, generated files, ambient declarations, methods and callbacks are excluded. Null input overloads require strictNullChecks: under loose null checking an earlier overload can mask their advertised result. No automatic rewrite changes a public overload or its runtime behavior.",
  ],
  references: ["https://www.typescriptlang.org/docs/handbook/2/functions.html#overload-signatures-and-the-implementation-signature"],
  examples: [
    { id: "correct-case-results", title: "Match each literal input with its result", outcome: "no-match", files: [{ path: "src/load.ts", source: 'function load(kind: "text"): {kind: "text"};\nfunction load(kind: "count"): {kind: "count"};\nfunction load(kind: "text" | "count"): {kind: "text" | "count"} { return kind === "text" ? {kind: "text"} : {kind: "count"}; }' }], focusPath: "src/load.ts", expectedCount: 0, public: true },
    { id: "inverted-case-results", title: "Do not swap domain variants behind overloads", outcome: "match", files: [{ path: "src/load.ts", source: 'function load(kind: "text"): {kind: "text"};\nfunction load(kind: "count"): {kind: "count"};\nfunction load(kind: "text" | "count"): {kind: "text" | "count"} { return kind === "text" ? {kind: "count"} : {kind: "text"}; }' }], focusPath: "src/load.ts", expectedCount: 2, public: true },
    {
      id: "safe-autofix",
      title: "Align an unused private overload group with its literal results",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; function choose(value: \"a\"): \"left\"; function choose(value: \"b\"): \"right\"; function choose(value: \"a\" | \"b\"): \"left\" | \"right\" { return value === \"a\" ? \"right\" : \"left\"; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; function choose(value: \"a\"): \"right\"; function choose(value: \"b\"): \"left\"; function choose(value: \"a\" | \"b\"): \"left\" | \"right\" { return value === \"a\" ? \"right\" : \"left\"; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 2,
    },
    {
      id: "safe-autofix-record",
      title: "Align an unused private overload group with its flat literal result",
      outcome: "match",
      files: [{ path: "src/autofix-record.ts", source: "export {}; function load(kind: \"text\"): {kind: \"text\"}; function load(kind: \"count\"): {kind: \"count\"}; function load(kind: \"text\" | \"count\"): {kind: \"text\" | \"count\"} { return kind === \"text\" ? {kind: \"count\"} : {kind: \"text\"}; }" }],
      fixedFiles: [{ path: "src/autofix-record.ts", source: "export {}; function load(kind: \"text\"): { \"kind\": \"count\" }; function load(kind: \"count\"): { \"kind\": \"text\" }; function load(kind: \"text\" | \"count\"): {kind: \"text\" | \"count\"} { return kind === \"text\" ? {kind: \"count\"} : {kind: \"text\"}; }" }],
      focusPath: "src/autofix-record.ts",
      expectedCount: 2,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "no-contradictory-overload-return", documentation: NO_CONTRADICTORY_OVERLOAD_RETURN_DOCUMENTATION,
  meta: {
    type: "problem", fixable: "code", docs: { description: NO_CONTRADICTORY_OVERLOAD_RETURN_DOCUMENTATION.summary }, schema: [],
    messages: { contradictoryReturn: "For input {{input}}, this returned literal contradicts the overload result {{expected}}. Preserve the input/result relationship in a checked case map, implementation or variant-specific operation." },
  }, defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text) || !context.sourceCode.parserServices?.program) return {};
    const services = ESLintUtils.getParserServices(context);
    const checker = services.program.getTypeChecker();
    const options = services.program.getCompilerOptions();
    const strictNulls = options.strictNullChecks ?? options.strict ?? false;
    return { FunctionDeclaration(node) {
      const implementation = services.esTreeNodeToTSNodeMap.get(node);
      const proof = implementationProof(implementation, checker);
      if (proof === undefined || (!strictNulls && proof.cases.some((entry) => entry.input.value === null))) return;
      const fix = privateOverloadFix(context.sourceCode, context.filename, node, implementation, proof, services);
      let offerFix = true;
      const reported = new Set<ts.Expression>();
      for (const entry of proof.cases) {
        const branch = (entry.input.value === proof.condition.value) === proof.equal ? proof.yes : proof.no;
        for (const literal of mismatches(branch, entry.output, checker)) {
          if (reported.has(literal.node)) continue;
          reported.add(literal.node);
          context.report({ node: services.tsNodeToESTreeNodeMap.get(literal.node), messageId: "contradictoryReturn", fix: offerFix ? fix : null, data: {
            input: JSON.stringify(entry.input.value), expected: checker.typeToString(entry.output),
          } });
          offerFix = false;
        }
      }
    } };
  },
});


function privateOverloadFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  filename: string,
  node: TSESTree.FunctionDeclaration,
  implementation: ts.FunctionDeclaration,
  proof: NonNullable<ReturnType<typeof implementationProof>>,
  services: ParserServicesWithTypeInformation,
): TSESLint.ReportFixFunction | null {
  const declarations = [implementation, ...proof.cases.map((entry) => entry.declaration)];
  const owners = declarations.map((declaration) => services.tsNodeToESTreeNodeMap.get(declaration));
  if (node.id === null || !isUnusedPrivateBinding(sourceCode, node, node.id, filename, owners) ||
    !declarations.every((declaration) => declaration.getSourceFile() === implementation.getSourceFile()) ||
    owners.some((owner) => owner.parent?.type !== AST_NODE_TYPES.Program || sourceCode.getCommentsInside(owner).length > 0 || sourceCode.getCommentsBefore(owner).length > 0)) return null;
  const parameter = directParameter(implementation);
  if (parameter === undefined || !primitiveResultSyntax(parameter.type) ||
    (implementation.type !== undefined && !directResultSyntax(implementation.type)) ||
    proof.cases.some((entry) => entry.declaration.type === undefined || !directResultSyntax(entry.declaration.type))) return null;
  const edits: { readonly node: TSESTree.Node; readonly text: string }[] = [];
  const checker = services.program.getTypeChecker();
  for (const entry of proof.cases) {
    const branch = (entry.input.value === proof.condition.value) === proof.equal ? proof.yes : proof.no;
    if (mismatches(branch, entry.output, checker).length === 0) continue;
    const annotation = entry.declaration.type;
    if (annotation === undefined) return null;
    const target = services.tsNodeToESTreeNodeMap.get(annotation);
    edits.push({ node: target, text: `${branchResultType(branch, sourceCode, services)}${sourceCode.getText(target).replace(/[^\r\n]/gu, "")}` });
  }
  return edits.length === 0 ? null : (fixer) => edits.map((edit) => fixer.replaceText(edit.node, edit.text));
}

function directResultSyntax(node: ts.TypeNode): boolean {
  if (ts.isParenthesizedTypeNode(node)) return directResultSyntax(node.type);
  if (ts.isUnionTypeNode(node)) return node.types.length <= LIMIT && node.types.every(directResultSyntax);
  if (!ts.isTypeLiteralNode(node)) return primitiveResultSyntax(node);
  return node.members.every((member) => ts.isPropertySignature(member) && propertyKey(member.name) !== undefined &&
    member.type !== undefined && primitiveResultSyntax(member.type));
}

function primitiveResultSyntax(node: ts.TypeNode): boolean {
  if (ts.isParenthesizedTypeNode(node)) return primitiveResultSyntax(node.type);
  if (ts.isUnionTypeNode(node)) return node.types.length <= LIMIT && node.types.every(primitiveResultSyntax);
  if (ts.isLiteralTypeNode(node)) return primitiveLiteral(node.literal) !== undefined;
  return node.kind === ts.SyntaxKind.StringKeyword || node.kind === ts.SyntaxKind.NumberKeyword ||
    node.kind === ts.SyntaxKind.BooleanKeyword || node.kind === ts.SyntaxKind.UndefinedKeyword || node.kind === ts.SyntaxKind.NeverKeyword;
}

function branchResultType(branch: Branch, sourceCode: Readonly<TSESLint.SourceCode>, services: ParserServicesWithTypeInformation): string {
  const valueType = (literal: LiteralValue): string => typeof literal.value === "string"
    ? sourceCode.getText(services.tsNodeToESTreeNodeMap.get(literal.node)) : String(literal.value);
  if (branch.kind === "literal") return valueType(branch.value);
  return `{ ${[...branch.values].map(([key, value]) => `${JSON.stringify(key)}: ${valueType(value)}`).join("; ")} }`;
}

function implementationProof(node: ts.FunctionDeclaration, checker: ts.TypeChecker) {
  const parameter = directParameter(node);
  if (!ts.isSourceFile(node.parent) || node.name === undefined || node.body?.statements.length !== 1 || node.typeParameters !== undefined || node.asteriskToken !== undefined ||
    node.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.AsyncKeyword) || parameter === undefined) return undefined;
  const returned = node.body.statements[0];
  if (returned === undefined || !ts.isReturnStatement(returned) || returned.expression === undefined) return undefined;
  const expression = unparen(returned.expression);
  if (!ts.isConditionalExpression(expression)) return undefined;
  const condition = equality(expression.condition, checker.getSymbolAtLocation(parameter.name), checker);
  const yes = branchValue(expression.whenTrue);
  const no = branchValue(expression.whenFalse);
  if (condition === undefined || yes === undefined || no === undefined) return undefined;
  const signature = checker.getSignatureFromDeclaration(node);
  if (signature === undefined) return undefined;
  const output = checker.getReturnTypeOfSignature(signature);
  if (!checker.isTypeAssignableTo(checker.getTypeAtLocation(yes.node), output) || !checker.isTypeAssignableTo(checker.getTypeAtLocation(no.node), output)) return undefined;
  const cases = overloadCases(node, output, checker);
  return cases === undefined ? undefined : { ...condition, yes, no, cases };
}

function directParameter(node: ts.FunctionDeclaration) {
  const parameter = node.parameters[0];
  if (node.parameters.length !== 1 || parameter === undefined || !ts.isIdentifier(parameter.name) || parameter.name.text === "this" ||
    parameter.type === undefined || parameter.questionToken !== undefined || parameter.dotDotDotToken !== undefined || parameter.initializer !== undefined) return undefined;
  return { name: parameter.name, type: parameter.type };
}

function overloadCases(node: ts.FunctionDeclaration, implementationOutput: ts.Type, checker: ts.TypeChecker): readonly LiteralCase[] | undefined {
  const declarations = node.name === undefined ? undefined : checker.getSymbolAtLocation(node.name)?.declarations;
  if (declarations === undefined || declarations.length < 3 || declarations.length > LIMIT + 1 || declarations.some((declaration) => !ts.isFunctionDeclaration(declaration))) return undefined;
  const cases: LiteralCase[] = [];
  const seen = new Set<Primitive>();
  const implementationParameter = directParameter(node);
  if (implementationParameter === undefined) return undefined;
  const implementationInput = checker.getTypeAtLocation(implementationParameter.type);
  for (const declaration of declarations) {
    if (!ts.isFunctionDeclaration(declaration) || declaration === node) continue;
    const parameter = directParameter(declaration);
    if (declaration.body !== undefined || declaration.typeParameters !== undefined || parameter === undefined || !ts.isLiteralTypeNode(parameter.type)) return undefined;
    const input = primitiveLiteral(parameter.type.literal);
    const signature = checker.getSignatureFromDeclaration(declaration);
    if (input === undefined || seen.has(input.value) || signature === undefined || !checker.isTypeAssignableTo(checker.getTypeAtLocation(parameter.type), implementationInput)) return undefined;
    const output = checker.getReturnTypeOfSignature(signature);
    if (!checker.isTypeAssignableTo(output, implementationOutput)) return undefined;
    seen.add(input.value);
    cases.push({ input, output, declaration });
  }
  return cases.length >= 2 ? cases : undefined;
}

function equality(expression: ts.Expression, parameter: ts.Symbol | undefined, checker: ts.TypeChecker) {
  const value = unparen(expression);
  if (parameter === undefined || !ts.isBinaryExpression(value) || (value.operatorToken.kind !== ts.SyntaxKind.EqualsEqualsEqualsToken && value.operatorToken.kind !== ts.SyntaxKind.ExclamationEqualsEqualsToken)) return undefined;
  for (const [tested, expected] of [[value.left, value.right], [value.right, value.left]] as const) {
    const named = unparen(tested);
    const condition = primitiveLiteral(expected);
    if (ts.isIdentifier(named) && checker.getSymbolAtLocation(named) === parameter && condition !== undefined) return { condition, equal: value.operatorToken.kind === ts.SyntaxKind.EqualsEqualsEqualsToken };
  }
  return undefined;
}

function branchValue(expression: ts.Expression): Branch | undefined {
  const node = unparen(expression);
  const literal = primitiveLiteral(node);
  if (literal !== undefined) return { kind: "literal", node, value: literal };
  if (!ts.isObjectLiteralExpression(node) || node.properties.length > LIMIT) return undefined;
  const values = new Map<string, LiteralValue>();
  for (const property of node.properties) {
    if (!ts.isPropertyAssignment(property)) return undefined;
    const name = propertyKey(property.name);
    const value = primitiveLiteral(property.initializer);
    if (name === undefined || name === "__proto__" || values.has(name) || value === undefined) return undefined;
    values.set(name, value);
  }
  return { kind: "record", node, values };
}

function mismatches(branch: Branch, expected: ts.Type, checker: ts.TypeChecker): readonly LiteralValue[] {
  if (branch.kind === "literal") {
    const literal = branch.value;
    return plainPrimitive(expected) && !checker.isTypeAssignableTo(checker.getTypeAtLocation(literal.node), expected) ? [literal] : [];
  }
  const result: LiteralValue[] = [];
  for (const [key, literal] of branch.values) {
    const property = checker.getPropertyOfType(expected, key);
    if (property === undefined) continue;
    const target = checker.getTypeOfSymbolAtLocation(property, branch.node);
    if (plainPrimitive(target) && !checker.isTypeAssignableTo(checker.getTypeAtLocation(literal.node), target)) result.push(literal);
  }
  return result;
}

function plainPrimitive(type: ts.Type): boolean {
  const members = type.isUnion() ? type.types : [type];
  const allowed = ts.TypeFlags.String | ts.TypeFlags.StringLiteral | ts.TypeFlags.Number | ts.TypeFlags.NumberLiteral | ts.TypeFlags.BooleanLiteral | ts.TypeFlags.Null | ts.TypeFlags.Undefined | ts.TypeFlags.Never;
  return members.length <= LIMIT && members.every((member) => (member.flags & allowed) !== 0 && (member.flags & (ts.TypeFlags.Enum | ts.TypeFlags.EnumLiteral)) === 0);
}

function primitiveLiteral(expression: ts.Expression): LiteralValue | undefined {
  const node = unparen(expression);
  if (ts.isStringLiteral(node)) return { node, value: node.text };
  if (node.kind === ts.SyntaxKind.TrueKeyword) return { node, value: true };
  if (node.kind === ts.SyntaxKind.FalseKeyword) return { node, value: false };
  if (node.kind === ts.SyntaxKind.NullKeyword) return { node, value: null };
  if (ts.isNumericLiteral(node) && Number.isFinite(Number(node.text))) return { node, value: Number(node.text) };
  if (ts.isPrefixUnaryExpression(node) && (node.operator === ts.SyntaxKind.MinusToken || node.operator === ts.SyntaxKind.PlusToken) && ts.isNumericLiteral(node.operand)) {
    const value = Number(node.operand.text) * (node.operator === ts.SyntaxKind.MinusToken ? -1 : 1);
    if (Number.isFinite(value)) return { node, value };
  }
  return undefined;
}

function propertyKey(name: ts.PropertyName): string | undefined {
  if (ts.isIdentifier(name) || ts.isStringLiteral(name)) return name.text;
  if (ts.isNumericLiteral(name) && Number.isFinite(Number(name.text))) return String(Number(name.text));
  return undefined;
}

function unparen(expression: ts.Expression): ts.Expression {
  let node = expression;
  while (ts.isParenthesizedExpression(node)) node = node.expression;
  return node;
}
